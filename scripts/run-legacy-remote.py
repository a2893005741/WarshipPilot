"""Field-run the product controller over WinRM before rebuilding its EXE.

No navigation coordinates live here. All input comes from original Lua yields.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.automation import TaskController
from backend.legacy_vm import identifier
from backend.store import Store, atomic_json


class Bridge:
    def __init__(self):
        self.process = subprocess.Popen(
            ['pwsh', '-NoProfile', '-NonInteractive', '-File', str(ROOT/'scripts/legacy-bridge.ps1')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')

    def request(self, operation, values=()):
        self.process.stdin.write(json.dumps({'operation': operation, 'values': values})+'\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('WinRM bridge closed')
        result = json.loads(line)
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result

    def ensure_input_ready(self, serial):
        assert serial == '127.0.0.1:16416'
        self.request('check')

    def click(self, serial, *coordinates):
        self.request('tap', coordinates)

    def swipe(self, serial, *coordinates):
        self.request('swipe', coordinates)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task', choices=['expedition', 'sortie'])
    parser.add_argument('--recover', action='store_true', help='Restore the previous field session battle counter')
    options = parser.parse_args()
    folder = ROOT/'evidence'/('field-'+options.task)
    class FieldRuntime:
        resources = ROOT
        serial = '127.0.0.1:16416'
        status = 'live'
        wake = threading.Event()
        store = Store(folder)
        adb = Bridge()
        raw = None
        frame = None

        def save_fault(self, reason):
            (folder/'fault.png').write_bytes(self.raw)

    runtime = FieldRuntime()
    original_event = runtime.store.event
    def event(message, level='info'):
        print(message, flush=True)
        original_event(message, level)
    runtime.store.event = event
    controller = TaskController(runtime)
    try:
        previous = json.loads((folder/'live.json').read_text()) if options.recover else {}
        controller.start(options.task)
        if options.recover and options.task=='sortie':
            controller.vm.globals[identifier('战斗次数C')] = int(previous.get('battles',0))
            controller.event('恢复上次实机已记录的原战斗计数：'+str(previous.get('battles',0)))
        while controller.vm:
            if (folder/'stop').exists():
                (folder/'stop').unlink()
                controller.stop('实机执行已手动停止')
                break
            if time.monotonic() < controller.delay_until:
                time.sleep(min(.2, controller.delay_until-time.monotonic()))
                continue
            if not controller.needs_frame:
                controller.tick(None)
                continue
            runtime.raw = base64.b64decode(runtime.adb.request('frame')['png'])
            runtime.frame = {'png': runtime.raw}
            (folder/'latest.png').write_bytes(runtime.raw)
            controller.tick(runtime.raw)
            atomic_json(folder/'live.json', controller.state())
        print(json.dumps(controller.state(), ensure_ascii=False), flush=True)
    finally:
        if controller.vm:
            controller.stop('实机执行会话结束')
        runtime.adb.process.stdin.close()
        runtime.adb.process.wait(timeout=15)
        runtime.store.close()


if __name__ == '__main__':
    main()
