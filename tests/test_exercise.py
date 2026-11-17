"""Replay the shipped 打演习 bytecode against synthetic game screens, no device I/O."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2

from module.api.alas.config_adapter import alas_schema
from module.config.schema import config_values, save_field, schema
from module.config.task_settings import EXECUTABLE, read_tasks
from module.legacy.vm import identifier
from module.runtime.controller import SUPPORTED, TaskController, legacy_next_run
from tests.synthetic import frame_for, paint_points
from tests.test_legacy_tasks import frame, vm
from tests.test_scheduler import Runtime


def png(image):
    return cv2.imencode('.png', cv2.cvtColor(image, cv2.COLOR_RGB2BGR))[1].tobytes()


class Replay:
    def __init__(self, legacy=None):
        self.machine = vm('exercise', legacy)
        self.clock = 10000
        self.machine.globals[b'host_sdk'] = self.sdk
        self.inputs = []

    def sdk(self, command, *args):
        return self.clock if int(command) == 84 else self.machine.sdk(command, *args)

    def run(self, raw, transition, until_tap=False):
        self.machine.feed(raw)
        for index in range(300):
            result = self.machine.resume() if index == 0 else self.machine.resume(0)
            if not isinstance(result, tuple):
                result = (result,)
            if result[0] == b'dead':
                return
            command, *args = result[1:]
            if command == 15:
                self.clock += float(args[0]) + 1
            elif command == 13:
                self.machine.feed(raw)
            elif command in (65, 219):
                self.inputs.append((command, args))
                if command == 65 and until_tap:
                    return
                raw = transition(command, args) or raw
        raise AssertionError('original exercise did not finish the scripted screen sequence')


class ExerciseReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The VM retains its established endpoint transform. Native Python
        # tasks have a different mapping, so paint VM fixtures with its mapping.
        with patch('module.vision.color.to_screen', TaskController.screen_point):
            cls.home = png(frame_for('港区'))
            cls.sortie = png(frame_for('出征-出征'))
            listing = frame_for('出征-演习')
            cls.first = png(paint_points(listing.copy(), '479|933|BEBCBF'))
            cls.second = png(paint_points(listing.copy(), '51|933|BEBCBF'))
            cls.prepare = png(frame_for('出征准备'))
            cls.formation = png(frame_for('选择阵型'))
            cls.night = png(frame_for('是否夜战'))

    def test_empty_two_pages_return_home_and_mark_completion(self):
        replay = Replay()
        state = ['home']
        swipes = []

        def transition(command, args):
            if command == 65:
                target = {'home': ('sortie', self.sortie), 'sortie': ('first', self.first),
                          'second': ('home', self.home)}[state[0]]
                state[0] = target[0]
                return target[1]
            if int(args[0]) == 2:
                swipes.append(True)
                state[0] = 'second'
                return self.second

        replay.run(self.home, transition)
        self.assertEqual((state[0], len(swipes)), ('home', 2))
        self.assertTrue(replay.machine.exercise_completed)
        self.assertEqual(replay.machine.globals[identifier('演习关闭加速')], 0)
        self.assertEqual(replay.machine.globals[identifier('战斗次数C')], 0)
        with TemporaryDirectory() as folder:
            controller = TaskController(Runtime(Path(folder)))
            controller.vm = replay.machine
            controller.failures['exercise'] = 2
            controller.result.update(task='exercise', page='港区', settings=read_tasks(Path(folder))['exercise'])
            controller.complete()
            self.assertEqual(controller.result['status'], 'completed')
            self.assertFalse(controller.busy)
            self.assertNotIn('exercise', controller.failures)
            restored = TaskController(Runtime(Path(folder)))
            self.assertEqual(restored.due, controller.due)

    def test_each_original_fleet_enum_selects_the_correct_fleet(self):
        for fleet, y in enumerate((156, 275, 388, 512)):
            with self.subTest(fleet=fleet):
                replay = Replay({'演习舰队': fleet})
                replay.run(self.prepare, lambda *a: None, until_tap=True)
                _, (x_actual, y_actual, *_) = replay.inputs[-1]
                self.assertLess(abs(x_actual - 440), 8)
                self.assertLess(abs(y_actual - y), 8)
                self.assertFalse(replay.machine.exercise_completed)

    def test_already_entered_or_disabled_function_cannot_report_completion(self):
        for disabled in (False, True):
            with self.subTest(disabled=disabled):
                replay = Replay()
                if disabled:
                    replay.machine.config['演习开关'] = False
                else:
                    replay.machine.globals[identifier('打演习时间戳')] = 123
                replay.run(self.home, lambda *a: None)
                self.assertFalse(replay.machine.exercise_completed)
                self.assertEqual(replay.inputs, [])

    def test_selected_formation_and_original_night_battle_are_executed(self):
        for raw, legacy, expected in ((self.formation, {'演习阵型': 4}, (55, 800)),
                                      (self.night, {'演习夜战': False}, (174, 379))):
            with self.subTest(legacy=legacy):
                replay = Replay(legacy)
                replay.run(raw, lambda *a: None, until_tap=True)
                _, (x, y, *_) = replay.inputs[-1]
                self.assertLess(abs(x - expected[0]), 8)
                self.assertLess(abs(y - expected[1]), 8)

    def test_completion_controller_rejects_early_return_and_preserves_retry(self):
        with TemporaryDirectory() as folder:
            controller = TaskController(Runtime(Path(folder)))
            controller.vm = vm('exercise')
            controller.result.update(task='exercise', page='港区', settings={'interval_minutes': 30})
            # Entry timestamp alone is not a completion marker.
            controller.vm.globals[identifier('打演习时间戳')] = 123
            with self.assertRaisesRegex(RuntimeError, '提前返回'):
                controller.complete()
            self.assertNotIn('exercise', controller.due)


class ExerciseVisionTest(unittest.TestCase):
    def test_refresh_helper_uses_physical_canvas_and_restores_it(self):
        machine = vm('exercise')
        helper = machine.globals[identifier('演习刷新次数是否用完')]
        pattern = ('186|791|EF9F24,189|791|EF9F24,192|791|EF9F24,195|794|EF9F24,'
                   '195|797|EF9F24,193|799|EF9F24,189|800|EF9F24,186|800|EF9F24,'
                   '181|799|EF9F24,179|795|EEA029')
        machine.feed(frame(pattern))
        self.assertEqual(helper(), 1)
        machine.feed(frame())
        self.assertEqual(helper(), 0)
        self.assertEqual(machine.canvas, (540, 960))

    def test_submarine_sixth_slot_searches_below_default_canvas(self):
        machine = vm('exercise')
        helper = machine.globals[identifier('演习是否有潜艇')]
        indicator = '273|1115|3FCAFC'
        pattern = ('295|1060|FFFFFF,289|1060|FFFFFF,279|1059|FFFFFF,295|1096|FBFAFA,'
                   '289|1096|FFFFFF,278|1097|F4F4F4,279|1074|FFFFFF,295|1083|FFFFFF,'
                   '283|1095|FFFFFF,292|1081|FFFFFF')
        machine.feed(frame(indicator + ',' + pattern))
        self.assertEqual(helper(6), 1)
        self.assertEqual(machine.canvas, (540, 960))
        machine.feed(frame(indicator))
        self.assertNotEqual(helper(6), 1)
        self.assertEqual(machine.canvas, (540, 960))

    def test_opponent_search_starts_at_bottom_right(self):
        machine = vm('exercise')
        machine.sdk(191, 0, 720, 1280)
        machine.feed(frame('40|752|FE9628,400|752|FE9628,30|753|FE9628,420|753|FE9628'))
        self.assertEqual(machine.sdk(168, 28, 752, 450, 753, b'FE9628', 2, .9), (420, 753))
        self.assertEqual(machine.find_colors(28, 752, 450, 753, b'FE9628', b'', 0, .9), (40, 752))

    def test_search_and_single_pixel_agree_at_default_canvas_corner(self):
        machine = vm('exercise')
        machine.feed(frame('719|1279|FFFFFF'))
        self.assertTrue(machine.compare(539, 959, b'FFFFFF', 1))
        self.assertEqual(machine.find_colors(539, 959, 539, 959, b'FFFFFF', b'', 0, 1), (539, 959))
        machine.feed(frame())
        self.assertEqual(machine.find_colors(539, 959, 539, 959, b'FFFFFF', b'', 0, 1), (-1, -1))


class ExerciseSettingsAndScheduleTest(unittest.TestCase):
    def test_failure_uses_configured_retry_interval(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            save_field(root, 'exercise.Scheduler.IntervalMinutes', 37)
            controller = TaskController(Runtime(root))
            controller.scheduler = True
            before = datetime.now(timezone.utc)
            controller.task_failed('exercise', 'test failure')
            due = datetime.fromisoformat(controller.due['exercise'])
            self.assertLess(abs((due - before).total_seconds() - 37 * 60), 2)
            self.assertTrue(controller.scheduler)

    def test_saved_original_parameters_reach_vm_and_manual_run_owns_switch(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in (('演习舰队', 3), ('演习阵型', 4), ('演习避潜艇', False)):
                save_field(root, f'exercise.Exercise.{name}', value)
            settings = read_tasks(root)['exercise']
            self.assertFalse(settings['enabled'])
            machine = vm('exercise', settings['legacy'] | {'演习开关': False})
            for key in ('演习舰队', '演习阵型', '演习避潜艇'):
                self.assertEqual(machine.config[key], settings['legacy'][key])
            self.assertTrue(machine.config['演习开关'])
            self.assertFalse(machine.config['战役开关'])
            save_field(root, 'exercise.Scheduler.Enable', True)
            self.assertTrue(config_values(root, 'exercise')['values']['Scheduler']['Enable'])
        self.assertIn('exercise', SUPPORTED)
        self.assertIn('exercise', EXECUTABLE)
        self.assertTrue(schema()['tasks']['exercise']['executable'])
        args = alas_schema()['args']['exercise']
        self.assertEqual(args['Scheduler']['Runs']['display'], 'hide')
        self.assertEqual(args['Exercise']['演习夜战']['display'], 'hide')
        self.assertEqual(args['Exercise']['NightBattle']['display'], 'disabled')

    def test_next_refresh_uses_local_midnight_noon_and_evening(self):
        settings = {'interval_minutes': 30, 'start_time': '00:00'}
        zone = timezone(timedelta(hours=8))
        # Set the OS-local conversion explicitly so this also runs on UTC CI.
        class LocalTime(datetime):
            def astimezone(self, tz=None):
                return super().astimezone(tz or zone)
        for hour, minute, next_hour, next_day in ((0, 0, 12, 18), (11, 59, 12, 18),
                                                 (12, 0, 18, 18), (17, 59, 18, 18),
                                                 (18, 0, 0, 19), (23, 59, 0, 19)):
            with self.subTest(hour=hour, minute=minute):
                current = LocalTime(2026, 11, 18, hour, minute, tzinfo=zone)
                due, reason = legacy_next_run('exercise', current, settings, {'演习完成': True}, 0)
                self.assertEqual(due, datetime(2026, 11, next_day, next_hour, tzinfo=zone))
                self.assertIn('刷新', reason)
        now = datetime(2026, 11, 18, 1, tzinfo=timezone.utc)
        due, _ = legacy_next_run('exercise', now, settings, {}, 0)
        self.assertEqual(due, now + timedelta(minutes=30))


if __name__ == '__main__':
    unittest.main()
