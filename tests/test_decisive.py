"""Replay the shipped 决战 bytecode against synthetic game screens, no device I/O."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from module.api.alas.config_adapter import alas_schema
from module.config.config import Config
from module.config.schema import save_field, schema
from module.config.task_settings import EXECUTABLE, read_tasks
from module.legacy.vm import LegacyHalt, LegacyVM, identifier
from module.runtime.controller import SUPPORTED, TaskController, legacy_next_run, next_daily
from tests.synthetic import frame_for, paint_points
from tests.test_exercise import png
from tests.test_legacy_tasks import vm
from tests.test_scheduler import Runtime

ROOT = Path(__file__).resolve().parents[1]
# 现在决战地图() == 6 (E6, the default 决战方案 0 -> |0-6|).
MAP_E6 = '363|646|F9F3FC,360|651|FFFEFF,352|664|FFFFFF,348|671|FFFFFF,343|683|FFFFFF,343|691|FFFFFF'
# 决战选关: the disk counter that makes 决战 ask 票用完了没().
TICKET_ICON = ('33|525|FFFFFF,37|525|FFFFFF,40|525|FFFFFF,43|525|FFFFFF,43|518|FFFFFF,'
               '43|531|FFFFFF,35|533|FFFFFF,35|516|FFFFFF')
# 票用完了没 on its 720x1280 canvas: the "0" disks digit.
NO_TICKETS = ('50|395|532F16,53|395|512C13,47|395|532F16,50|391|FFFFFF,53|391|FFFFFF,47|391|FFFFFF,'
              '47|398|FFFFFF,53|398|FFFFFF,57|395|FFFFFF,43|395|FFFFFF,44|392|FFFFFF,56|397|FFFFFF,'
              '52|391|FFFFFF,47|391|FFFFFF')


def paint_physical(image, expression):
    """Paint 'x|y|BBGGRR' points of the 720x1280 canvas (1:1 with the frame)."""
    for point in expression.split(','):
        x, y, color = point.split('|')
        image[719 - int(x), int(y)] = [int(color[i:i + 2], 16) for i in (4, 2, 0)]
    return image


class Replay:
    def __init__(self, legacy=None, data=None, general=None):
        self.machine = LegacyVM(ROOT, data or Path(mkdtemp()), 'decisive',
                                {'runs': 1, 'legacy': legacy or {}, 'general_legacy': general or {}},
                                lambda *a: None, lambda *a: None)
        self.logs = []
        self.machine.log = self.logs.append
        self.clock = 10000
        self.machine.globals[b'host_sdk'] = self.sdk
        self.inputs = []

    def sdk(self, command, *args):
        return self.clock if int(command) == 84 else self.machine.sdk(command, *args)

    def run(self, raw, transition):
        self.machine.feed(raw)
        for index in range(600):
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
                raw = transition(command, args) or raw
                self.machine.feed(raw)
        raise AssertionError('original decisive did not finish the scripted screen sequence')


class DecisiveReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Paint 540x960 fixtures with the VM's endpoint mapping (see test_exercise).
        with patch('module.vision.color.to_screen', TaskController.screen_point):
            cls.home = png(frame_for('港区'))
            select = frame_for('决战选关')
            paint_points(select, MAP_E6)
            paint_points(select, TICKET_ICON)
            cls.no_tickets = png(paint_physical(select, NO_TICKETS))

    def test_tickets_used_up_returns_home_and_schedules_next_day(self):
        replay = Replay()
        replay.run(self.no_tickets, lambda *a: self.home)
        self.assertEqual(replay.machine.decisive_end, 'tickets')
        self.assertIn('票用完了,结束决战', replay.logs)
        # 收远征 walked home with one original input after 决战 returned.
        self.assertEqual(len(replay.inputs), 1)
        with TemporaryDirectory() as folder:
            root = Path(folder)
            controller = TaskController(Runtime(root))
            controller.vm = replay.machine
            controller.failures['decisive'] = 1
            settings = read_tasks(root)['decisive']
            controller.result.update(task='decisive', page='港区', settings=settings)
            controller.complete()
            self.assertEqual(controller.result['status'], 'completed')
            self.assertNotIn('decisive', controller.failures)
            due = datetime.fromisoformat(controller.due['decisive'])
            self.assertEqual(due.astimezone().strftime('%H:%M'), settings['start_time'])

    def test_daily_limit_from_saved_record_returns_before_any_input(self):
        with TemporaryDirectory() as folder:
            data = Path(folder)
            record = data / 'log' / 'legacy-files' / '记录文件.txt'
            record.parent.mkdir(parents=True)
            today = datetime.now().strftime('%m%d')
            # 决战限制次数 index 1 = 2 decisive battles = 6 BOSS fights.
            record.write_text(json.dumps({'养成记录': 0, '日期': today, '决战BOSS次数': 6}), encoding='utf-8')
            replay = Replay({'决战限制次数': 1}, data=data)
            self.assertEqual(replay.machine.globals[identifier('TABLE')]['决战BOSS次数'.encode()], 6)
            replay.run(self.home, lambda *a: None)
            self.assertEqual(replay.machine.decisive_end, 'limit')
            self.assertEqual(replay.inputs, [])
            # A lower count on another day is reset by the original itself, not here.
            record.write_text(json.dumps({'日期': '0101', '决战BOSS次数': 6}), encoding='utf-8')
            replay = Replay({'决战限制次数': 1}, data=data)
            self.assertEqual(replay.machine.globals[identifier('TABLE')]['日期'.encode()], b'0101')

    def test_ticket_exchange_runs_first_only_when_enabled(self):
        # Exchange button greyed out: 决战换票 has nothing left to exchange.
        with patch('module.vision.color.to_screen', TaskController.screen_point):
            exchanged = png(paint_points(frame_for('决战换票'), '252|584|A5A5A5'))
        disabled = Replay({'决战换票开关': False})
        disabled.run(self.no_tickets, lambda *a: self.home)
        self.assertEqual(len(disabled.inputs), 1)

        replay = Replay({'决战换票开关': True})
        screens = [exchanged, self.no_tickets]
        replay.run(self.no_tickets, lambda *a: screens.pop(0) if screens else self.home)
        _, (x, y, *_) = replay.inputs[0]
        self.assertLess(abs(float(x) - 38) + abs(float(y) - 343), 16)  # 决战选关 -> 换票
        self.assertEqual(replay.machine.decisive_end, 'tickets')

    def test_stage_clear_choice_keeps_rewards_and_continues(self):
        # 确认通关/放弃 after a stage BOSS: the original recognizes no page there
        # and asks for a game restart (live run, 2026-11-18).
        image = np.zeros((720, 1280, 3), np.uint8)
        for name, x, y in (('decisive-clear-title.png', 276, 254), ('decisive-abandon-title.png', 766, 254)):
            template = cv2.imdecode(np.fromfile(ROOT / 'assets/game' / name, np.uint8), cv2.IMREAD_COLOR)
            h, w = template.shape[:2]
            image[y:y + h, x:x + w] = cv2.cvtColor(template, cv2.COLOR_BGR2RGB)
        image[600:620, 600:690] = [34, 143, 246]  # 确认
        choice = png(image)
        screens = [choice, self.no_tickets]
        replay = Replay()
        replay.run(choice, lambda *a: screens.pop(0) if screens else self.home)
        taps = [TaskController.screen_point(*args[:2]) for _, args in replay.inputs[:2]]
        self.assertLess(abs(taps[0][0] - 400) + abs(taps[0][1] - 340), 20)  # 确认通关
        self.assertLess(abs(taps[1][0] - 646) + abs(taps[1][1] - 610), 20)  # 确认
        self.assertEqual(replay.machine.decisive_end, 'tickets')
        # Other tasks never act on it.
        machine = vm('sortie')
        machine.feed(choice)
        self.assertFalse(machine.decisive_clear())


class DecisivePlatformTest(unittest.TestCase):
    def test_switch_and_forced_desktop_values_survive_saved_settings(self):
        machine = Replay({'决战开关': False}, general={'保持加速': True, '拆船方式': 2}).machine
        self.assertTrue(machine.config['决战开关'])
        self.assertFalse(machine.config['保持加速'])
        self.assertEqual(machine.config['拆船方式'], 2)

    def test_original_date_is_month_day(self):
        machine = vm('decisive')
        today = datetime.now().strftime('%m%d').encode()
        self.assertEqual(machine.globals[identifier('当前日期')](), today)
        self.assertEqual(machine.globals[identifier('TABLE')]['日期'.encode()], today)

    def test_drop_snapshot_is_saved_under_data(self):
        with TemporaryDirectory() as folder:
            replay = Replay(data=Path(folder))
            replay.machine.feed(png(frame_for('港区')))
            self.assertEqual(replay.machine.sdk(186, '/sdcard/Pictures/决战11月18日.png'.encode()), 1)
            self.assertTrue((Path(folder) / 'screenshots/decisive/决战11月18日.png').is_file())
            replay.machine.sdk(186, b'../../evil')
            self.assertTrue((Path(folder) / 'screenshots/decisive/evil.png').is_file())

    def test_new_ship_stop_setting_halts_instead_of_looping(self):
        machine = vm('decisive')
        with self.assertRaises(LegacyHalt):
            machine.sdk(10, '新船上锁停止'.encode())
        with TemporaryDirectory() as folder:
            controller = TaskController(Runtime(Path(folder)))
            controller.scheduler = True
            controller.vm = machine
            controller.result.update(task='decisive', status='running')

            def halt(raw):
                raise LegacyHalt('决战捞到新船')
            controller.step = halt
            controller.tick(None)
            self.assertFalse(controller.scheduler)
            self.assertEqual(controller.result['status'], 'stopped')
            self.assertIsNone(controller.vm)
            self.assertNotIn('decisive', controller.failures)

    def test_bath_wait_keeps_progress_and_does_not_sortie(self):
        ticks = []
        with TemporaryDirectory() as folder:
            machine = LegacyVM(ROOT, Path(folder), 'decisive', {'legacy': {}}, lambda *a: None,
                               lambda *a: None, progress=lambda: ticks.append(1))
            machine.globals[identifier('出征战斗')]()
            machine.sdk(10, '决战慢修等待,900秒后再检查'.encode())
        self.assertEqual(len(ticks), 2)

    def test_end_reasons_from_original_log_lines(self):
        machine = vm('decisive')
        for message, reason in (('今天的决战次数打完了,晚上12点更新\n今天打了2次决战', 'limit'),
                                ('仓库满了,停止决战,转远征', 'dock_full'),
                                ('票用完了,结束决战', 'tickets')):
            machine.sdk(10, message.encode())
            self.assertEqual(machine.decisive_end, reason)


class DecisiveScheduleAndSettingsTest(unittest.TestCase):
    now = datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)
    settings = {'interval_minutes': 45, 'start_time': '00:10'}

    def test_next_run(self):
        for end in ('limit', 'tickets'):
            due, reason = legacy_next_run('decisive', self.now, self.settings, {'决战结束': end}, 0)
            self.assertEqual(due, next_daily(self.now, '00:10'))
            self.assertIn('次日', reason)
        for end in ('dock_full', None):
            due, _ = legacy_next_run('decisive', self.now, self.settings, {'决战结束': end}, 0)
            self.assertEqual(due, self.now + timedelta(minutes=45))

    def test_failure_uses_configured_retry_interval(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            save_field(root, 'decisive.Scheduler.IntervalMinutes', 25)
            controller = TaskController(Runtime(root))
            controller.scheduler = True
            before = datetime.now(timezone.utc)
            controller.task_failed('decisive', 'test failure')
            due = datetime.fromisoformat(controller.due['decisive'])
            self.assertLess(abs((due - before).total_seconds() - 25 * 60), 2)

    def test_task_is_executable_with_its_original_fields(self):
        self.assertIn('decisive', SUPPORTED)
        self.assertIn('decisive', EXECUTABLE)
        self.assertTrue(schema()['tasks']['decisive']['executable'])
        args = alas_schema()['args']['decisive']
        self.assertNotIn('display', args['Scheduler']['Enable'])
        self.assertEqual(args['Scheduler']['Runs']['display'], 'hide')
        self.assertEqual(args['Decisive']['决战开关']['display'], 'hide')
        moved = ('换票资源', '351', 'U96', 'U1206', '鹦鹉螺', 'U1405', '鲃鱼', '开局SL潜艇')
        for key in moved:
            self.assertIn(key, args['Decisive'])
            self.assertNotIn(key, alas_schema()['args']['control']['Control'])

    def test_values_saved_on_the_old_control_page_carry_over(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            config = Config(root)
            config.save_section('Tasks', {'control': {'Control': {'U96': True, '换票资源': 3}}})
            legacy = read_tasks(root)['decisive']['legacy']
            self.assertEqual((legacy['U96'], legacy['换票资源']), (True, 3))
            save_field(root, 'decisive.Decisive.U96', False)
            self.assertFalse(read_tasks(root)['decisive']['legacy']['U96'])


class InputBurstTest(unittest.TestCase):
    def test_original_tap_burst_counts_as_one_repeated_action(self):
        with TemporaryDirectory() as folder:
            runtime = Runtime(Path(folder))
            clicks = []
            runtime.adb = SimpleNamespace(ensure_input_ready=lambda serial: None,
                                          click=lambda serial, x, y: clicks.append((x, y)))
            controller = TaskController(runtime)
            # 教官用技能: five taps 100 ms apart, on several map visits a minute.
            for _ in range(5):
                for _ in range(5):
                    controller.input('tap', (300, 600))
            self.assertEqual(len(clicks), 25)
            with patch('module.runtime.controller.BURST', 0):
                with self.assertRaisesRegex(RuntimeError, '重复十次'):
                    for _ in range(11):
                        controller.input('tap', (100, 100))


if __name__ == '__main__':
    unittest.main()
