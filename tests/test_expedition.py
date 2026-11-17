"""Native expedition task on synthetic frames and (locally) on recorded frames."""
from pathlib import Path
import random
import unittest

import cv2
import numpy as np

from module.expedition import expedition as exp
from module.expedition.expedition import Expedition
from module.ui import assets
from module.ui.navigation import GameStuckError
from module.vision.color import to_screen
from tests.synthetic import DETECTOR, ScriptedDevice, frame_for, handlers, paint_points

ROOT = Path(__file__).resolve().parents[1]


def slot_name(x):
    return f'槽位{x}'


BUTTONS = {b.name: to_screen(b.x, b.y) for b in (
    assets.SORTIE, assets.BACK, assets.TAB_EXPEDITION, assets.TAB_EXERCISE, assets.CONTINUE,
    exp.CONTINUE_CONFIRM, exp.CONTINUE_CANCEL, exp.CHAPTER_PREV, exp.CHAPTER_NEXT)}
BUTTONS.update({slot_name(x): to_screen(x, exp.SLOT_Y) for x in exp.SLOTS})


def home(badge):
    image = frame_for('港区').copy()
    return paint_points(image, exp.FINISHED_BADGE) if badge else image


def expedition_list(lit=()):
    image = frame_for('出征-远征').copy()
    for x in lit:
        paint_points(image, f'{x}|{exp.SLOT_Y}|{exp.SLOT_COLOR}')
    return image


def dialog():
    image = frame_for('战斗结果').copy()
    for x, y, template in exp.CONTINUE_TEMPLATES:
        h, w = template.shape[:2]
        image[y:y + h, x:x + w] = template
    (X, Y), rgb = exp.CONTINUE_BUTTON_PIXEL
    image[Y, X] = rgb
    return image


def task(device, survey=False, **kwargs):
    return Expedition(device, detector=DETECTOR, handlers=handlers(), interval=0,
                      sleep=lambda s: None, rng=random.Random(1), survey=survey, **kwargs)


def chapter(index, timers=None, lit=()):
    """出征-远征 on chapter `index`: a distinct chapter column, optionally a live
    timer panel (tests/fixtures/expedition) and lit 收获奖励 slots."""
    base = expedition_list(lit)
    image = np.zeros_like(base)
    image[100:650, 0:300] = 40 + 30 * index
    if timers:
        crop = cv2.imdecode(np.fromfile(ROOT / 'tests/fixtures/expedition' / f'{timers}.png', np.uint8),
                            cv2.IMREAD_COLOR)
        image[100:680, 1040:1250] = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    painted = base.any(axis=2)  # keep every pixel the page / slot checks look at
    image[painted] = base[painted]
    return image


class FramesTest(unittest.TestCase):
    def test_synthetic_frames(self):
        self.assertEqual(DETECTOR.detect(home(True)), '港区')
        self.assertEqual(DETECTOR.detect(expedition_list([387])), '出征-远征')
        self.assertEqual(exp.collectable_slot(expedition_list([172, 66])), 172)
        self.assertIsNone(exp.collectable_slot(expedition_list()))
        self.assertTrue(exp.continue_dialog(dialog()))
        self.assertFalse(exp.continue_dialog(frame_for('战斗结果')))


class FlowTest(unittest.TestCase):
    def game(self, start='home+', landing='演习', transitions=None):
        screens = {'home+': home(True), 'home': home(False), '演习': frame_for('出征-演习'),
                   'list2': expedition_list([387, 280]), 'list1': expedition_list([280]),
                   'list0': expedition_list(), 'result': frame_for('战斗结果'), 'dialog': dialog(),
                   'result1': frame_for('战斗结果'), 'dialog1': dialog()}
        t = {('home+', '出征'): landing, ('演习', '远征标签'): 'list2',
             ('list2', slot_name(387)): 'result', ('result', '点击继续'): 'dialog',
             ('dialog', '继续远征-确认'): 'list1', ('dialog', '继续远征-取消'): 'list1',
             ('list1', slot_name(280)): 'result1', ('result1', '点击继续'): 'dialog1',
             ('dialog1', '继续远征-确认'): 'list0', ('dialog1', '继续远征-取消'): 'list0',
             ('list0', '返回'): 'home'}
        t.update(transitions or {})
        return ScriptedDevice(screens, t, start, BUTTONS)

    def test_collect_all_and_redeploy(self):
        device = self.game()
        result = task(device).run()
        self.assertEqual((result.collected, result.redeployed), (2, 2))
        self.assertEqual(device.clicks, [
            ('home+', '出征'), ('演习', '远征标签'),
            ('list2', slot_name(387)), ('result', '点击继续'), ('dialog', '继续远征-确认'),
            ('list1', slot_name(280)), ('result1', '点击继续'), ('dialog1', '继续远征-确认'),
            ('list0', '返回')])

    def test_no_redeploy_cancels_dialog(self):
        device = self.game()
        result = task(device, redeploy=False).run()
        self.assertEqual((result.collected, result.redeployed), (2, 0))
        self.assertIn(('dialog', '继续远征-取消'), device.clicks)

    def test_nothing_finished_sends_no_input(self):
        device = self.game(start='home')
        result = task(device).run()
        self.assertEqual((result.collected, device.clicks), (0, []))

    def test_badge_without_collectable_slot_stops(self):
        # Finished expedition in another chapter: original would loop forever.
        device = self.game(start='home+', landing='list0', transitions={('list0', '返回'): 'home+'})
        with self.assertRaises(GameStuckError):
            task(device).run()
        self.assertEqual(device.clicks.count(('list0', '返回')), 2)


def live_tile(name):
    """A live frame's chapter column around the selected tile (x 20-294, y 360-432)."""
    crop = cv2.imdecode(np.fromfile(ROOT / 'tests/fixtures/expedition' / f'{name}.png', np.uint8), cv2.IMREAD_COLOR)
    image = np.zeros((720, 1280, 3), np.uint8)
    image[360:432, 20:294] = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return exp.chapter_signature(image)


class ChapterSignatureTest(unittest.TestCase):
    """On the live list neighbouring chapters look alike; the tile must not."""

    def test_every_pair_of_live_chapters_differs(self):
        chapters = [f'tile-ch{i}' for i in range(1, 11)]
        for a in range(len(chapters)):
            for b in range(a + 1, len(chapters)):
                with self.subTest(a=chapters[a], b=chapters[b]):
                    self.assertFalse(exp.same_chapter(live_tile(chapters[a]), live_tile(chapters[b])))

    def test_frames_of_one_chapter_match(self):
        self.assertTrue(exp.same_chapter(live_tile('tile-ch4'), live_tile('tile-ch4b')))
        self.assertTrue(exp.same_chapter(live_tile('tile-ch9'), live_tile('tile-ch9b')))


class SurveyTest(unittest.TestCase):
    """After collecting, every chapter's countdowns are read (first to last)."""

    def test_reads_countdowns_on_every_chapter(self):
        screens = {'home': home(False), 'ch1': chapter(1, 'mixed'), 'ch2': chapter(2, 'idle'),
                   'ch3': chapter(3, 'single')}
        t = {('home', '出征'): 'ch2',
             ('ch2', '上一章'): 'ch1', ('ch1', '下一章'): 'ch2', ('ch2', '下一章'): 'ch3',
             ('ch3', '返回'): 'home'}
        device = ScriptedDevice(screens, t, 'home', BUTTONS)
        result = task(device, survey=True).run()
        self.assertEqual(result.remaining, [2 * 3600 + 57 * 60 + 22, 4 * 3600 + 56 * 60 + 48])
        self.assertEqual(result.unreadable, 0)
        self.assertEqual(device.clicks, [
            ('home', '出征'), ('ch2', '上一章'), ('ch1', '上一章'), ('ch1', '上一章'), ('ch1', '下一章'),
            ('ch2', '下一章'), ('ch3', '下一章'), ('ch3', '下一章'), ('ch3', '返回')])

    def test_collects_finished_expedition_found_on_another_chapter(self):
        screens = {'home+': home(True), 'home': home(False), 'chA': chapter(2, 'single'),
                   'chB+': chapter(1, lit=[387]), 'chB': chapter(1, 'mixed'),
                   'result': frame_for('战斗结果'), 'dialog': dialog()}
        t = {('home+', '出征'): 'chA', ('chA', '上一章'): 'chB+',
             ('chB+', slot_name(387)): 'result', ('result', '点击继续'): 'dialog',
             ('dialog', '继续远征-确认'): 'chB', ('chB', '下一章'): 'chA', ('chA', '返回'): 'home'}
        device = ScriptedDevice(screens, t, 'home+', BUTTONS)
        result = task(device, survey=True).run()
        self.assertEqual((result.collected, result.redeployed), (1, 1))
        self.assertEqual(result.remaining, [2 * 3600 + 57 * 60 + 22, 4 * 3600 + 56 * 60 + 48])

    def test_waits_for_slow_chapter_list(self):
        """Live game: the list changes well after the tap; frames in between
        still show the old chapter and must not read as 'first/last chapter'."""

        class SlowDevice(ScriptedDevice):
            def click(self, x, y):
                current = self.state
                super().click(x, y)
                if self.clicks[-1][1] in ('上一章', '下一章'):
                    self.pending, self.state, self.delay = self.state, current, 4

            def screenshot(self):
                if getattr(self, 'delay', 0):
                    self.delay -= 1
                    if not self.delay:
                        self.state = self.pending
                return super().screenshot()

        screens = {'home': home(False), 'ch1': chapter(1, 'short'), 'ch2': chapter(2, 'idle'),
                   'ch3': chapter(3, 'single')}
        t = {('home', '出征'): 'ch3', ('ch3', '上一章'): 'ch2', ('ch2', '上一章'): 'ch1',
             ('ch1', '下一章'): 'ch2', ('ch2', '下一章'): 'ch3', ('ch3', '返回'): 'home'}
        result = task(SlowDevice(screens, t, 'home', BUTTONS), survey=True).run()
        self.assertEqual(result.remaining, [59 * 60 + 16, 4 * 3600 + 56 * 60 + 48])

    def test_lost_chapter_tap_is_retried(self):
        """Live game: a tap during the list's easing is dropped; the next
        chapter must still be read instead of ending the walk."""

        class LossyDevice(ScriptedDevice):
            dropped = False

            def click(self, x, y):
                current = self.state
                super().click(x, y)
                if (current, self.clicks[-1][1]) == ('ch2', '下一章') and not self.dropped:
                    self.dropped, self.state = True, current

        screens = {'home': home(False), 'ch1': chapter(1, 'short'), 'ch2': chapter(2, 'idle'),
                   'ch3': chapter(3, 'single')}
        t = {('home', '出征'): 'ch1', ('ch1', '下一章'): 'ch2', ('ch2', '下一章'): 'ch3',
             ('ch3', '返回'): 'home'}
        result = task(LossyDevice(screens, t, 'home', BUTTONS), survey=True).run()
        self.assertEqual(result.remaining, [59 * 60 + 16, 4 * 3600 + 56 * 60 + 48])

    def test_without_survey_nothing_finished_sends_no_input(self):
        device = ScriptedDevice({'home': home(False)}, {}, 'home', BUTTONS)
        result = task(device).run()
        self.assertEqual((result.remaining, device.clicks), (None, []))


def load(name):
    image = cv2.imdecode(np.fromfile(ROOT / 'evidence' / name, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


RECORDED = {'home+': 'nav-sortie.png', 'list': 'expedition-running.png', 'result': 'expedition-reward.png',
            'dialog': 'expedition-list-after-collect.png',
            'list0': 'field-sortie/runs/419ea6c8b72b429ead9d1cca4764024a/1794823417720.png',
            'home': 'v0.4-exe-final.png'}


@unittest.skipUnless(all((ROOT / 'evidence' / f).exists() for f in RECORDED.values()), 'local evidence frames not present')
class RecordedFlowTest(unittest.TestCase):
    def test_one_collection_on_real_frames(self):
        screens = {k: load(v) for k, v in RECORDED.items()}
        t = {('home+', '出征'): 'list', ('list', slot_name(387)): 'result', ('result', '点击继续'): 'dialog',
             ('dialog', '继续远征-确认'): 'list0', ('list0', '返回'): 'home'}
        device = ScriptedDevice(screens, t, 'home+', BUTTONS)
        result = task(device).run()
        self.assertEqual((result.collected, result.redeployed), (1, 1))
        self.assertEqual([c[1] for c in device.clicks],
                         ['出征', slot_name(387), '点击继续', '继续远征-确认', '返回'])


if __name__ == '__main__':
    unittest.main()
