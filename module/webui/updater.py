"""Git update check and deferred handover after the current task completes."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import threading

from deploy.git import Git
from module.config.config import Config
from module.logger import atomic_json, now
from module.version import VERSION


class Updater:
    def __init__(self, root, launch, busy, shutdown, event, quiesce=lambda value: None, stop_event=None):
        self.root, self.launch = Path(root), launch
        self.busy, self.shutdown, self.event = busy, shutdown, event
        self.quiesce = quiesce
        self.stop_event = stop_event or threading.Event()
        self.config = Config(root)
        self.status = {'state': 'idle', 'progress': '', 'error': '', 'latest': None, 'checked': ''}
        result_file = self.root / 'log' / 'update-result.json'
        if result_file.exists():
            import json
            result = json.loads(result_file.read_text(encoding='utf-8'))
            if not result.get('ok', True):
                self.status.update(state='error', error=result.get('error', '上次更新失败'))
        self.lock = threading.RLock()
        self.operation = threading.Lock()

    def save_settings(self, auto_check=None):
        with self.config.lock:
            value = self.config.deploy()
            if auto_check is not None:
                value['Update']['AutoCheck'] = bool(auto_check)
            self.config.save_deploy(value)
        return self.state()

    def state(self):
        with self.lock:
            deployment = self.config.deploy()
            return {'version': VERSION, 'branch': deployment['Git']['Branch'],
                    'auto_check': deployment['Update']['AutoCheck'], **deepcopy(self.status)}

    def check(self):
        if not self.operation.acquire(blocking=False):
            return self.state()
        try:
            with self.lock:
                if self.status['state'] in ('waiting', 'restarting'):
                    return self.state()
                self.status.update(state='checking', error='')
            change = Git(self.root).inspect()
            latest = {'tag': change['target'][:10], 'version': change['target'],
                      'current': change['current'], 'commits': change['commits'],
                      'notes': '\n'.join(f"{c['sha'][:8]} {c['date']} {c['subject']}" for c in change['commits'])}
            with self.lock:
                self.status.update(state='available' if change['commits'] else 'current',
                                   latest=latest, checked=now(), error='')
        except Exception as exc:
            with self.lock:
                self.status.update(state='error', error=str(exc)[:700], checked=now())
        finally:
            self.operation.release()
        return self.state()

    def install(self):
        with self.lock:
            if self.status['state'] != 'available':
                raise ValueError('请先检查可用更新')
            if not self.config.deploy()['Git']['AutoUpdate']:
                raise ValueError('deploy.yaml 中已关闭自动更新')
            Git(self.root).ensure_clean()
            self.status.update(state='waiting', error='', progress='等待当前任务结束')
        try:
            self.quiesce(True)
        except Exception:
            with self.lock:
                self.status['state'] = 'available'
            raise
        self.event('已请求源码更新，等待当前任务结束后重启')
        threading.Thread(target=self._wait_and_restart, name='source-update', daemon=True).start()
        return self.state()

    def _wait_and_restart(self):
        try:
            while not self.stop_event.is_set():
                if not self.busy():
                    self._handover()
                    return
                self.stop_event.wait(0.25)
        except Exception as exc:
            self.quiesce(False)
            with self.lock:
                self.status.update(state='error', progress='', error=str(exc)[:700])
            self.event(f'更新启动失败：{exc}', 'warning')

    def _handover(self):
        arguments = self.root / 'log' / 'update-arguments.json'
        atomic_json(arguments, self.launch.get('argv', ['--no-browser']))
        command = [sys.executable, '-m', 'deploy.installer', '--root', str(self.root),
                   '--wait-pid', str(os.getpid()), '--restart', '--target',
                   self.status['latest']['version'], '--gui-args-file', str(arguments)]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        log = self.root / 'log' / 'installer.log'
        with log.open('ab') as stream:
            try:
                subprocess.Popen(command, cwd=self.root, close_fds=True, stdout=stream, stderr=stream,
                                 creationflags=flags | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0))
            except OSError:
                subprocess.Popen(command, cwd=self.root, close_fds=True, stdout=stream, stderr=stream,
                                 creationflags=flags)
        with self.lock:
            self.status.update(state='restarting', progress='')
        self.shutdown()

    def start_auto_check(self, stop_event, interval=6 * 3600):
        def loop():
            while not stop_event.wait(15 if not self.status['checked'] else interval):
                if self.config.deploy()['Update']['AutoCheck']:
                    self.check()
        threading.Thread(target=loop, name='update-check', daemon=True).start()
