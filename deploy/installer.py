"""Update a clean source checkout, synchronize dependencies, then restart."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import traceback
import time
import urllib.request

from deploy import adb, pip
from deploy.git import Git
from deploy.lock import instance_lock, AlreadyRunning
from module.config.config import Config
from module.config.migration import migrate
from module.logger import atomic_json, now


def wait_pid(pid):
    if not pid:
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # already exited
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.WaitForSingleObject(handle, 120000) != 0:
            raise RuntimeError('后台未能在两分钟内退出，已取消更新')
    finally:
        kernel.CloseHandle(handle)


def start_gui(root, argv):
    executable = Path(Config(root).executable('Python')).with_name('pythonw.exe')
    return subprocess.Popen([str(executable), str(root / 'gui.py'), '--root', str(root), *argv],
                     cwd=root, close_fds=True,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def install(root, target=None, skip_update=False):
    migrate(root)
    config = Config(root)
    previous = None
    try:
        if not skip_update and config.deploy()['Git']['AutoUpdate']:
            previous = Git(root).apply(target)['current']
        elif target:
            raise ValueError('自动更新已关闭')
        pip.sync(root)
        adb.check(root)
    except Exception:
        if previous:
            rollback(root, previous)
        raise
    return previous


def rollback(root, previous):
    git = Git(root)
    git.ensure_clean()
    git.run('reset', '--hard', previous)
    pip.sync(root)


def wait_healthy(root, process, argv):
    port = Config(root).deploy()['WebUI']['Port']
    if '--port' in argv:
        port = int(argv[argv.index('--port') + 1])
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                health = json.load(response)
                if health.get('product') == 'WarshipPilot' and health.get('pid') == process.pid:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    raise RuntimeError('更新后后台未能启动，正在恢复原提交')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--wait-pid', type=int, default=0)
    parser.add_argument('--restart', action='store_true')
    parser.add_argument('--wait-gui', action='store_true')
    parser.add_argument('--target')
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--gui-args-file', type=Path)
    args, gui_args = parser.parse_known_args()
    root = args.root.resolve()
    if args.gui_args_file:
        gui_args = json.loads(args.gui_args_file.read_text(encoding='utf-8'))
    wait_pid(args.wait_pid)
    result = root / 'log' / 'update-result.json'
    try:
        with instance_lock(root):
            previous = install(root, args.target, args.skip_update)
    except AlreadyRunning:
        if '--no-browser' not in gui_args:
            import webbrowser
            web = Config(root).deploy()['WebUI']
            webbrowser.open(f"http://127.0.0.1:{web['Port']}/#key={web['AccessCode']}")
        return
    except Exception as exc:
        atomic_json(result, {'ok': False, 'time': now(), 'error': str(exc)})
        (root / 'log' / 'installer-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        if args.wait_pid and args.restart:
            # Git/network/uv errors must not leave the console permanently unavailable.
            start_gui(root, gui_args)
        raise
    if args.restart:
        process = start_gui(root, gui_args)
        try:
            wait_healthy(root, process, gui_args)
        except Exception as exc:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            if previous:
                with instance_lock(root):
                    rollback(root, previous)
                start_gui(root, gui_args)
            atomic_json(result, {'ok': False, 'time': now(), 'error': str(exc)})
            raise
    atomic_json(result, {'ok': True, 'time': now()})
    if args.restart and args.wait_gui:
        # Keep the scheduled task's wrapper alive while its GUI child runs.
        process.wait()


if __name__ == '__main__':
    main()
