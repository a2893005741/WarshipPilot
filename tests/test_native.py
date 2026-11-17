"""Native task runner: device gate, pause/stop, input ownership."""
import threading
import time
import unittest

from module.expedition.expedition import CHAPTER_NEXT, CHAPTER_PREV
from module.runtime.native import GatedDevice, NativeRun, TaskStopped
from module.ui import assets
from module.vision.color import to_screen
from tests.synthetic import frame_for


class FakeEmulator:
    class config:
        Emulator_ScreenshotMethod = 'fake'
        Emulator_ControlMethod = 'fake'

    def __init__(self, image):
        self.image = image
        self.clicks = []

    def screenshot(self):
        return self.image

    def click(self, x, y):
        self.clicks.append((x, y))


class FakeAdb:
    def __init__(self):
        self.checks = 0

    def ensure_input_ready(self, serial):
        self.checks += 1


class FakeStore:
    def __init__(self):
        self.events = []

    def event(self, message, level='info'):
        self.events.append(message)


class FakeRuntime:
    def __init__(self, image):
        self.io_lock = threading.Lock()
        self.emulator = FakeEmulator(image)
        self.adb = FakeAdb()
        self.store = FakeStore()
        self.serial = '127.0.0.1:16416'
        self.frames = 0

    def publish_frame(self, rgb, **meta):
        self.frames += 1


class GateTest(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime(frame_for('港区'))
        self.run = NativeRun(self.runtime, 'expedition', {}, lambda run, status: None)
        self.device = GatedDevice(self.runtime, self.run)

    def test_click_checks_foreground_first(self):
        self.device.click(10, 20)
        self.assertEqual(self.runtime.adb.checks, 1)
        self.assertEqual(self.runtime.emulator.clicks, [(10, 20)])
        self.assertEqual(self.run.inputs, 1)

    def test_screenshot_publishes_preview(self):
        self.device.screenshot()
        self.assertEqual(self.runtime.frames, 1)

    def test_stop_blocks_all_device_calls(self):
        self.run.stop('测试停止')
        with self.assertRaises(TaskStopped):
            self.device.click(1, 1)
        with self.assertRaises(TaskStopped):
            self.device.screenshot()
        self.assertEqual(self.runtime.emulator.clicks, [])

    def test_pause_holds_input_until_resume(self):
        self.run.paused.set()
        done = threading.Event()
        threading.Thread(target=lambda: (self.device.click(5, 5), done.set()), daemon=True).start()
        time.sleep(0.3)
        self.assertEqual(self.runtime.emulator.clicks, [])
        self.run.paused.clear()
        self.assertTrue(done.wait(2))
        self.assertEqual(self.runtime.emulator.clicks, [(5, 5)])

    def test_stop_while_paused_never_clicks(self):
        self.run.paused.set()
        errors = []
        t = threading.Thread(target=lambda: self._try_click(errors), daemon=True)
        t.start()
        time.sleep(0.2)
        self.run.stop('停止')
        t.join(2)
        self.assertEqual(errors, ['stopped'])
        self.assertEqual(self.runtime.emulator.clicks, [])

    def _try_click(self, errors):
        try:
            self.device.click(1, 1)
        except TaskStopped:
            errors.append('stopped')


class PagedEmulator(FakeEmulator):
    """港区 <-> 出征-远征 (one empty chapter), switched by 出征 / 返回."""
    SORTIE, BACK = to_screen(assets.SORTIE.x, assets.SORTIE.y), to_screen(assets.BACK.x, assets.BACK.y)

    def __init__(self):
        super().__init__(frame_for('港区'))
        self.pages = {'港区': frame_for('港区'), '出征-远征': frame_for('出征-远征')}

    def click(self, x, y):
        super().click(x, y)
        if (x, y) == self.SORTIE:
            self.image = self.pages['出征-远征']
        elif (x, y) == self.BACK:
            self.image = self.pages['港区']


class RunTest(unittest.TestCase):
    def test_expedition_with_nothing_finished_reads_countdowns_and_returns(self):
        runtime = FakeRuntime(frame_for('港区'))  # no finished badge
        runtime.emulator = PagedEmulator()
        finished = []
        run = NativeRun(runtime, 'expedition', {}, lambda r, status: finished.append(status))
        run.start()
        run.thread.join(20)
        self.assertEqual(finished, ['completed'], run.error)
        self.assertEqual(run.result.collected, 0)
        self.assertEqual(run.result.remaining, [])  # surveyed: no fleet away
        prev, next_ = (to_screen(b.x, b.y) for b in (CHAPTER_PREV, CHAPTER_NEXT))
        self.assertEqual(runtime.emulator.clicks,
                         [PagedEmulator.SORTIE, prev, next_, PagedEmulator.BACK])


if __name__ == '__main__':
    unittest.main()
