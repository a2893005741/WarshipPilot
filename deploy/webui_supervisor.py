"""Keep the launcher-owned process alive while WebUI updates replace workers.

Only the standard library is imported here so runtime dependency DLLs are not
held open while the installer synchronizes the environment.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

UPDATE_EXIT_CODE = 85
SUPERVISED_ENV = 'WARSHIP_WEBUI_SUPERVISED'


def supervise(root, argv, entry=None):
    root = Path(root).resolve()
    entry = Path(entry or root / 'gui.py')
    env = dict(os.environ, **{SUPERVISED_ENV: '1'})
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen([sys.executable, str(entry), '--webui-worker', *argv],
                               cwd=root, env=env, close_fds=True, creationflags=flags)
    while True:
        try:
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                # A console Ctrl+C must not leave hidden workers behind.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               capture_output=True, timeout=15, creationflags=flags)
                process.wait(timeout=5)
            raise
        if code != UPDATE_EXIT_CODE:
            return code
        request_file = root / 'log' / 'update-request.json'
        try:
            request = json.loads(request_file.read_text(encoding='utf-8'))
            target = request['target']
            if not isinstance(target, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', target):
                raise ValueError('target')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('网页更新请求无效，请重新启动后台后检查更新') from exc
        request_file.unlink()
        command = [sys.executable, '-m', 'deploy.installer', '--root', str(root),
                   '--restart', '--wait-gui', '--supervised', '--target', target,
                   '--gui-args-file', str(root / 'log' / 'update-arguments.json')]
        with (root / 'log' / 'installer.log').open('ab') as stream:
            # Inherit the launcher's Job. Its Stop/Exit still owns the complete
            # worker tree; the supervisor itself never exits during an update.
            process = subprocess.Popen(command, cwd=root, env=env, close_fds=True,
                                       stdout=stream, stderr=stream, creationflags=flags)
