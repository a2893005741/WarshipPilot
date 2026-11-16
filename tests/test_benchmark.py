"""Method benchmark logic with a fake device (no emulator needed)."""
import unittest

import numpy as np

from module.device import benchmark
from module.device.compat import RequestHumanTakeover
from module.vision.color import to_screen
from tests.synthetic import DETECTOR, frame_for


class FakeDevice:
    """Screens per page; per-method frame transforms and click behaviour."""

    def __init__(self, page='出征-远征', lossy=(), dead=(), unavailable=()):
        self.page = page
        self.lossy, self.dead, self.unavailable = set(lossy), set(dead), set(unavailable)
        self.frames = {name: frame_for(name) for name in ('出征-远征', '出征-演习')}
        self.clicks = []

    def screenshot(self, method=None):
        if method in self.unavailable:
            raise RequestHumanTakeover('not here')
        image = self.frames[self.page]
        if method in self.lossy:
            noisy = image.astype(np.int16) + 60
            return np.clip(noisy, 0, 255).astype(np.uint8)
        return image

    def click(self, x, y, method=None):
        self.clicks.append((method, x, y))
        if method in self.dead:
            return
        for page, button in benchmark.TAB_PAIR:
            bx, by = to_screen(button.x, button.y)
            if abs(bx - x) <= 6 and abs(by - y) <= 6:
                self.page = page


class ScreenshotBenchmarkTest(unittest.TestCase):
    def test_lossy_and_unavailable_methods_are_rejected(self):
        device = FakeDevice(lossy={'scrcpy'}, unavailable={'DroidCast'})
        results = benchmark.benchmark_screenshot(device, ['nemu_ipc', 'scrcpy', 'DroidCast'], DETECTOR, total=3)
        by = {r.method: r for r in results}
        self.assertTrue(by['nemu_ipc'].ok)
        self.assertEqual(by['nemu_ipc'].detail['differing_checks'], 0)
        self.assertFalse(by['scrcpy'].ok)
        self.assertGreater(by['scrcpy'].detail['differing_checks'], 0)
        self.assertFalse(by['DroidCast'].ok)
        self.assertIn('不可用', by['DroidCast'].error)
        self.assertEqual(benchmark.recommend(results), 'nemu_ipc')
        self.assertEqual(device.clicks, [])  # screenshot tests never tap


class ClickBenchmarkTest(unittest.TestCase):
    def test_reacting_methods_pass_and_game_returns_to_start_tab(self):
        device = FakeDevice(dead={'minitouch'})
        results = benchmark.benchmark_click(device, ['ADB', 'minitouch', 'MaaTouch'], DETECTOR, rounds=1)
        by = {r.method: r for r in results}
        self.assertTrue(by['ADB'].ok)
        self.assertEqual(by['ADB'].detail['reacted'], 2)
        self.assertFalse(by['minitouch'].ok)
        self.assertTrue(by['MaaTouch'].ok)
        self.assertEqual(device.page, '出征-远征')

    def test_refuses_outside_sortie_tabs(self):
        device = FakeDevice()
        device.frames['港区'] = frame_for('港区')
        device.page = '港区'
        with self.assertRaises(RequestHumanTakeover):
            benchmark.benchmark_click(device, ['ADB'], DETECTOR)
        self.assertEqual(device.clicks, [])


if __name__ == '__main__':
    unittest.main()
