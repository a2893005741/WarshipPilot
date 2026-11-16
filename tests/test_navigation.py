"""Page graph navigation on synthetic frames."""
import random
import unittest

from module.ui import assets
from module.ui.navigation import UI, GameStuckError, UnknownPageError
from module.vision.color import to_screen
from tests.synthetic import DETECTOR, ScriptedDevice, frame_for, handlers

import numpy as np

BUTTONS = {b.name: to_screen(b.x, b.y) for b in (
    assets.SORTIE, assets.BACK, assets.TAB_SORTIE, assets.TAB_EXERCISE, assets.TAB_EXPEDITION,
    assets.TAB_CAMPAIGN, assets.TAB_DECISIVE, assets.CONTINUE)}
TABS = {'出征-出征': '出征标签', '出征-演习': '演习标签', '出征-远征': '远征标签',
        '出征-战役': '战役标签', '出征-决战': '决战标签'}


def game(start, landing='出征-演习', extra_screens=None, extra_transitions=None):
    """港区 + five 出征 tabs. 出征 lands on `landing` (the last used tab in game)."""
    screens = {name: frame_for(name) for name in ('港区', *TABS)}
    transitions = {('港区', '出征'): landing}
    for tab in TABS:
        transitions[(tab, '返回')] = '港区'
        for other, button in TABS.items():
            transitions[(tab, button)] = other
    screens.update(extra_screens or {})
    transitions.update(extra_transitions or {})
    return ScriptedDevice(screens, transitions, start, BUTTONS)


def ui(device):
    return UI(device, DETECTOR, handlers(), interval=0, sleep=lambda s: None, rng=random.Random(0))


class SyntheticFramesTest(unittest.TestCase):
    def test_every_graph_page_synthesises(self):
        for name in ('港区', *TABS):
            with self.subTest(page=name):
                self.assertEqual(DETECTOR.detect(frame_for(name)), name)


class GotoTest(unittest.TestCase):
    def test_main_to_expedition_replans_from_landing_tab(self):
        device = game('港区', landing='出征-演习')
        self.assertEqual(ui(device).ui_goto('出征-远征'), '出征-远征')
        self.assertEqual(device.clicks, [('港区', '出征'), ('出征-演习', '远征标签')])

    def test_landing_on_destination_needs_one_click(self):
        device = game('港区', landing='出征-远征')
        ui(device).ui_goto('出征-远征')
        self.assertEqual(device.clicks, [('港区', '出征')])

    def test_tab_to_main(self):
        device = game('出征-战役')
        ui(device).ui_goto('港区')
        self.assertEqual(device.clicks, [('出征-战役', '返回')])

    def test_every_tab_reachable_from_every_tab(self):
        for start in TABS:
            for target in TABS:
                with self.subTest(start=start, target=target):
                    device = game(start)
                    ui(device).ui_goto(target)
                    expected = [] if start == target else [(start, TABS[target])]
                    self.assertEqual(device.clicks, expected)

    def test_ui_ensure_does_not_click_when_already_there(self):
        device = game('出征-远征')
        ui(device).ui_ensure('出征-远征')
        self.assertEqual(device.clicks, [])


class FallbackTest(unittest.TestCase):
    def test_result_screen_is_dismissed_with_original_default(self):
        # 战斗结果 is also the expedition result screen; original taps (270,10).
        device = game('战斗结果', extra_screens={'战斗结果': frame_for('战斗结果')},
                      extra_transitions={('战斗结果', '点击继续'): '出征-远征'})
        ui(device).ui_goto('港区')
        self.assertEqual(device.clicks, [('战斗结果', '点击继续'), ('出征-远征', '返回')])

    def test_unknown_screen_stops_without_input(self):
        black = np.zeros((720, 1280, 3), np.uint8)
        device = game('黑屏', extra_screens={'黑屏': black})
        with self.assertRaises(UnknownPageError):
            ui(device).ui_goto('港区', unknown_limit=3)
        self.assertEqual(device.clicks, [])

    def test_ineffective_click_stops(self):
        device = game('出征-战役', extra_transitions={('出征-战役', '返回'): '出征-战役'})
        with self.assertRaises(GameStuckError):
            ui(device).ui_goto('港区', repeat_limit=3)
        self.assertEqual(len(device.clicks), 4)


if __name__ == '__main__':
    unittest.main()
