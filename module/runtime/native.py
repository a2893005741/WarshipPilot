"""Run native (Python) tasks against the selected device in a worker thread.

The task sees a small device: screenshot() / click(x, y). Every call passes
through a gate that honours pause and stop before touching the emulator,
holds the runtime's device lock for the actual I/O (one input owner), and
rechecks that the game is in the foreground before each input.
"""
import threading
import time
import traceback

from module.expedition.expedition import Expedition

NATIVE_TASKS = {'expedition': Expedition}


class TaskStopped(Exception):
    pass


class GatedDevice:
    def __init__(self, runtime, run):
        self.runtime, self.run = runtime, run

    def gate(self):
        while self.run.paused.is_set() and not self.run.stopped.is_set():
            self.run.stopped.wait(0.1)
        if self.run.stopped.is_set():
            raise TaskStopped(self.run.stop_reason or '任务已停止')

    def screenshot(self):
        self.gate()
        with self.runtime.io_lock:
            started = time.monotonic()
            image = self.runtime.emulator.screenshot()
            cost = round((time.monotonic() - started) * 1000, 1)
        self.runtime.publish_frame(image, backend=self.runtime.emulator.config.Emulator_ScreenshotMethod,
                                   capture_ms=cost)
        return image

    def click(self, x, y):
        self.gate()
        with self.runtime.io_lock:
            self.runtime.adb.ensure_input_ready(self.runtime.serial)
            self.runtime.emulator.click(x, y)
        self.run.inputs += 1
        self.run.last_action = f'tap {int(x)},{int(y)}'
        self.runtime.store.event(f'原生任务 · {self.run.last_action}')

    def sleep(self, seconds):
        self.run.stopped.wait(seconds)
        self.gate()


class NativeRun:
    def __init__(self, runtime, task, settings, on_done):
        self.runtime, self.task, self.settings = runtime, task, settings
        self.paused, self.stopped = threading.Event(), threading.Event()
        self.stop_reason = ''
        self.inputs = 0
        self.last_action = ''
        self.result = None
        self.error = ''
        self.worker = None
        self.on_done = on_done
        self.thread = threading.Thread(target=self._main, name=f'native-{task}', daemon=True)

    def start(self):
        self.thread.start()

    def stop(self, reason):
        self.stop_reason = reason
        self.stopped.set()

    @property
    def page(self):
        pages = getattr(getattr(self.worker, 'result', None), 'pages', None)
        return pages[-1] if pages else ''

    def _main(self):
        device = GatedDevice(self.runtime, self)
        status = 'completed'
        try:
            cls = NATIVE_TASKS[self.task]
            kwargs = {'redeploy': self.settings.get('redeploy', True)} if self.task == 'expedition' else {}
            self.worker = cls(device, sleep=device.sleep, **kwargs)
            self.result = self.worker.run()
        except TaskStopped as exc:
            status, self.error = 'stopped', str(exc)
        except Exception as exc:
            status, self.error = 'fault', f'{type(exc).__name__}: {exc}'[:700]
            self.runtime.store.event('原生任务异常：' + traceback.format_exc()[-1500:], 'warning')
        self.on_done(self, status)
