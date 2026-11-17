"""Original 打战役 / 收任务 through the Lua VM, and their next-run rules."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from module.legacy.vm import LegacyVM, identifier
from module.runtime.controller import legacy_next_run, next_daily

ROOT = Path(__file__).resolve().parents[1]
# 战役剩余次数, 720 branch: "0" attempts left drawn on the 720x1280 canvas.
NO_ATTEMPTS = ('103|225|424242,107|225|CFCFCF,115|225|CFCFCF,118|225|424242,123|226|CFCFCF,'
               '110|221|424242,110|216|CFCFCF,115|222|424242,115|229|424242,106|222|424242')


def vm(task, legacy=None):
    return LegacyVM(ROOT, Path(tempfile.mkdtemp()), task, {'runs': 1, 'legacy': legacy or {}},
                    lambda *a: None, lambda *a: None)


def frame(points=''):
    """1280x720 BGR PNG with the given 720x1280-canvas points painted."""
    image = np.full((720, 1280, 3), 128, np.uint8)
    for point in filter(None, points.split(',')):
        x, y, color = point.split('|')
        bgr = [int(color[i:i + 2], 16) for i in (0, 2, 4)]  # script colours are BBGGRR
        image[719 - int(x), int(y)] = bgr                     # 720x1280 canvas is 1:1 with the frame
    return cv2.imencode('.png', image)[1].tobytes()


class LegacyEntryTest(unittest.TestCase):
    def test_entries_and_campaign_switch(self):
        self.assertEqual(vm('campaign').config['战役开关'], True)
        self.assertEqual(vm('campaign', {'战役SL': True}).config['战役SL'], False)
        for task in ('campaign', 'exercise', 'reward', 'sortie'):
            self.assertIsNotNone(vm(task).resume)
        with self.assertRaises(ValueError):
            vm('decisive')

    def test_campaign_attempts_read_on_physical_canvas(self):
        machine = vm('campaign')
        attempts = machine.globals[identifier('战役剩余次数')]
        machine.feed(frame(NO_ATTEMPTS))
        self.assertEqual(attempts(), 0)
        machine.feed(frame())
        self.assertEqual(attempts(), '未知'.encode())
        # The function restores the default canvas and GetScreen afterwards.
        self.assertEqual((machine.canvas, machine.physical, machine.sdk(44, 0)), ((540, 960), False, 540))

    def test_game_restart_is_refused(self):
        machine = vm('campaign')
        for command in (177, 222):
            with self.assertRaises(RuntimeError):
                machine.sdk(command, b'com.huanmeng.zhanjian2')


class LegacyNextRunTest(unittest.TestCase):
    now = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
    settings = {'interval_minutes': 30, 'start_time': '00:10'}

    def test_campaign_done_for_the_day(self):
        due, reason = legacy_next_run('campaign', self.now, self.settings, {'打战役时间戳': 5000}, 9000)
        self.assertEqual(due, next_daily(self.now, '00:10'))
        self.assertEqual(due.astimezone().strftime('%H:%M'), '00:10')
        self.assertGreater(due, self.now)
        self.assertIn('用完', reason)

    def test_campaign_bathing_waits_like_the_original(self):
        due, _ = legacy_next_run('campaign', self.now, self.settings, {'战役泡澡时间戳': 60_000}, 120_000)
        self.assertEqual(due, self.now + timedelta(milliseconds=60_000 + 900_000 - 120_000))

    def test_interval_otherwise(self):
        for task in ('campaign', 'reward', 'sortie'):
            due, _ = legacy_next_run(task, self.now, self.settings, {}, 0)
            self.assertEqual(due, self.now + timedelta(minutes=30))

    def test_next_daily_is_strictly_later(self):
        local = self.now.astimezone()
        today = local.replace(hour=0, minute=10, second=0, microsecond=0)
        self.assertEqual(next_daily(today.astimezone(timezone.utc), '00:10'),
                         (today + timedelta(days=1)).astimezone(timezone.utc))


if __name__ == '__main__':
    unittest.main()
