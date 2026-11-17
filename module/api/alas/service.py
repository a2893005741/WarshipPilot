"""WarshipPilot's runtime behind AzurPilot's WebUI methods (single instance).

Each method returns the shape of AzurPilot frontend/src/api/types.ts. Azur Lane
only shell features (announcements, plugins, wallpapers, launcher) answer
empty so the reused shell keeps working without them.
"""
import base64
from datetime import datetime, timezone
import json
import threading

import cv2

from module.api.alas.config_adapter import ConfigAdapter, to_local_text
from module.api.alas.protocol import ApiError
from module.config.task_settings import read_tasks

INSTANCE = '舰R'
LEVELS = {'info': 'INFO', 'warning': 'WARNING', 'error': 'ERROR', 'debug': 'DEBUG'}
UPDATE_STATES = {'idle': 'idle', 'current': 'idle', 'checking': 'checking', 'available': 'available',
                 'waiting': 'wait', 'restarting': 'reload', 'error': 'failed'}


class WarshipService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.config = ConfigAdapter(runtime, INSTANCE)

    def check(self, instance):
        if instance != INSTANCE:
            raise ApiError('NOT_FOUND', f'实例不存在：{instance}')

    # --- instances / overview -------------------------------------------------------
    def status(self):
        automation = self.runtime.automation
        update = self.runtime.updater.state() if self.runtime.updater else {}
        if update.get('state') in ('waiting', 'restarting'):
            return 'updating'
        if automation.scheduler or automation.busy:
            return 'running'
        if automation.result.get('status') == 'fault':
            return 'error'
        return 'stopped'

    def instances(self):
        automation = self.runtime.automation
        return [{'name': INSTANCE, 'status': self.status(), 'serial': self.runtime.serial or '',
                 'server': 'cn', 'region': 'cn',
                 'currentTask': automation.result.get('task') if automation.busy else None}]

    def overview(self, instance=INSTANCE):
        self.check(instance)
        from module.runtime.controller import SUPPORTED
        automation = self.runtime.automation
        tasks = read_tasks(self.runtime.store.root)
        current = datetime.now(timezone.utc)
        rows = []
        for name in SUPPORTED:
            if not tasks[name]['enabled']:
                continue
            due = automation.due.get(name)
            if automation.busy and automation.result.get('task') == name:
                state = 'running'
            elif due is None or datetime.fromisoformat(due) <= current:
                state = 'pending'
            else:
                state = 'waiting'
            rows.append({'name': name, 'nextRun': to_local_text(due), 'pending': state == 'pending', 'state': state})
        order = {'running': 0, 'pending': 1, 'waiting': 2}
        rows.sort(key=lambda row: (order[row['state']], row['nextRun']))
        device = self.runtime.device_state()
        return {'instance': INSTANCE, 'revision': self.config.revision(), 'status': self.status(), 'tasks': rows,
                'resources': [],
                'emulator': {'Serial': self.runtime.serial or '', 'Status': self.runtime.status,
                             'ScreenshotMethod': device['screenshot_method'],
                             'ControlMethod': device['control_method']}}

    def scheduler(self, instance, start):
        self.check(instance)
        self.runtime.automation.control('scheduler-start' if start else 'scheduler-stop')
        return self.overview()

    def run_task(self, instance, task):
        self.check(instance)
        from module.runtime.controller import SUPPORTED
        if task not in SUPPORTED:
            raise ApiError('UNSUPPORTED', '该任务尚未接入执行')
        with self.runtime.lock:
            self.runtime.automation.start(task)
        self.runtime.wake.set()
        return self.overview()

    def run_now(self, instance, task):
        self.check(instance)
        return self.config.run_now(task)

    # --- logs / preview ----------------------------------------------------------------
    def logs(self, instance, after=0):
        self.check(instance)
        events, newest = self.runtime.store.events_after(after)
        entries = []
        for event in events:
            moment = datetime.fromisoformat(event['time']).astimezone()
            level = LEVELS.get(event['level'], 'INFO')
            entries.append({'id': event['id'], 'level': level,
                            'text': f"{level} {moment:%Y-%m-%d %H:%M:%S} │ {event['message']}"})
        return {'instance': INSTANCE, 'cursor': newest, 'reset': after == 0 or after > newest, 'entries': entries}

    def frame_id(self):
        frame = self.runtime.frame
        return frame.get('id') if frame else None

    def capture(self, instance=INSTANCE):
        self.check(instance)
        frame = self.runtime.frame
        if not frame:
            return {'instance': INSTANCE, 'image': None, 'capturedAt': None}
        rgb = getattr(frame, 'rgb', None)
        if rgb is not None:
            ok, data = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
            image = 'data:image/jpeg;base64,' + base64.b64encode(data.tobytes()).decode() if ok else None
        else:
            image = 'data:image/png;base64,' + base64.b64encode(frame['png']).decode()
        return {'instance': INSTANCE, 'image': image, 'capturedAt': frame.get('time')}

    # --- error records (log/error/<id>) ---------------------------------------------------
    def error_folder(self, record):
        folder = self.runtime.store.root / 'log' / 'error' / record
        if not folder.is_dir():
            raise ApiError('NOT_FOUND', '错误记录不存在')
        return folder

    def errors(self, instance, offset, limit):
        self.check(instance)
        base = self.runtime.store.root / 'log' / 'error'
        folders = sorted((f for f in base.glob('*') if f.is_dir() and len(f.name) == 32),
                         key=lambda f: f.stat().st_mtime, reverse=True)
        entries = [{'id': f.name, 'timestamp': int(f.stat().st_mtime * 1000),
                    'screenshots': len(list(f.glob('*.png'))), 'has_log': (f / 'events.json').exists()}
                   for f in folders[offset:offset + limit]]
        return {'instance': INSTANCE, 'total': len(folders), 'enabled': True, 'entries': entries}

    def error_detail(self, instance, record):
        self.check(instance)
        folder = self.error_folder(record)
        lines = []
        try:
            state = json.loads((folder / 'state.json').read_text(encoding='utf-8'))
            lines.append(f"原因：{state.get('reason', '')}")
        except (OSError, ValueError):
            pass
        try:
            for event in reversed(json.loads((folder / 'events.json').read_text(encoding='utf-8'))):
                lines.append(f"{event.get('time', '')} {event.get('level', '')} {event.get('message', '')}")
        except (OSError, ValueError):
            pass
        text = '\n'.join(lines)
        return {'instance': INSTANCE, 'id': record, 'images': sorted(p.name for p in folder.glob('*.png')),
                'log': text[-200_000:] if text else None, 'truncated': len(text) > 200_000}

    def error_file(self, instance, record, name):
        self.check(instance)
        folder = self.error_folder(record)
        if '/' in name or '\\' in name or name.startswith('.'):
            raise ApiError('INVALID_PARAMS', '文件名不正确')
        path = folder / name
        if not path.is_file():
            raise ApiError('NOT_FOUND', '文件不存在')
        media = 'image/png' if name.endswith('.png') else 'application/json' if name.endswith('.json') else 'text/plain'
        return {'filename': name, 'content': base64.b64encode(path.read_bytes()).decode(), 'media_type': media}

    # --- deploy settings (config/deploy.yaml) ---------------------------------------------
    SETTINGS = [
        ('WebUI', '控制台', [('WebUI.Host', 'input', '监听地址', '0.0.0.0 允许局域网访问；修改后重启生效。'),
                            ('WebUI.Port', 'int', '端口', '修改后重启生效。'),
                            ('WebUI.AccessCode', 'password', '访问密码',
                             '保存后立即生效，已打开的页面保持登录；其他设备需用新密码重新登录。至少 6 位，留空表示不修改。')]),
        ('Git', '源码更新', [('Git.Repository', 'input', '更新源', '可填镜像地址；留空使用 origin。'),
                            ('Git.Branch', 'input', '分支', '默认 main。'),
                            ('Git.AutoUpdate', 'checkbox', '允许更新', '关闭后不安装新版本。')]),
        ('Update', '检查更新', [('Update.AutoCheck', 'checkbox', '自动检查', '每 6 小时检查一次更新源。')]),
    ]

    def settings(self):
        from module.config.config import Config
        deploy = Config(self.runtime.store.root).deploy()
        groups = []
        for key, label, fields in self.SETTINGS:
            items = []
            for path, kind, name, help_text in fields:
                section, field = path.split('.')
                value = '' if kind == 'password' else deploy.get(section, {}).get(field)
                items.append({'key': path, 'type': kind, 'label': name, 'help': help_text, 'value': value, 'options': []})
            groups.append({'key': key, 'label': label, 'fields': items})
        return {'groups': groups, 'notice': '', 'demo': False}

    def save_settings(self, values):
        from module.config.config import Config
        allowed = {path: kind for _, _, fields in self.SETTINGS for path, kind, _, _ in fields}
        config = Config(self.runtime.store.root)
        updated = []
        with config.lock:
            deploy = config.deploy()
            for path, value in values.items():
                if path not in allowed:
                    raise ApiError('NOT_FOUND', f'设置不存在：{path}')
                kind = allowed[path]
                if kind == 'password' and value == '':
                    continue
                if kind == 'checkbox' and not isinstance(value, bool) or kind == 'int' and (
                        type(value) is not int or not 1 <= value <= 65535) or kind in ('input', 'password') and not isinstance(value, str):
                    raise ApiError('INVALID_PARAMS', f'设置值不正确：{path}')
                if kind == 'password' and (len(value) < 6 or len(value) > 128 or value != value.strip()):
                    raise ApiError('INVALID_PARAMS', '访问密码需 6–128 位，且首尾不能有空格')
                section, field = path.split('.')
                deploy.setdefault(section, {})[field] = value
                updated.append(path)
            config.save_deploy(deploy)
        if 'WebUI.AccessCode' in updated:
            self.runtime.access_code = values['WebUI.AccessCode']
            self.runtime.store.event('访问密码已修改，立即生效')
        return {'updated': updated}

    # --- updater -------------------------------------------------------------------------
    def update_status(self):
        updater = self.runtime.updater
        if updater is None:
            return {'state': 'idle', 'localHead': None, 'upstreamHead': None, 'branch': '', 'ahead': 0, 'behind': 0,
                    'available': False, 'busy': False, 'canApply': False, 'canCancel': False, 'error': ''}
        state = updater.state()
        latest = state.get('latest') or {}
        local = getattr(self.runtime, 'commit', '') or latest.get('current') or None
        available = state['state'] == 'available'
        return {'state': UPDATE_STATES.get(state['state'], state['state']), 'localHead': local,
                'upstreamHead': latest.get('version') or local, 'branch': state.get('branch', ''),
                'ahead': 0, 'behind': len(latest.get('commits') or []), 'available': available,
                'busy': state['state'] in ('checking', 'waiting', 'restarting'), 'canApply': available,
                'canCancel': False, 'error': state.get('error', '')}

    def commits(self, offset, limit):
        from deploy.git import Git
        git = Git(self.runtime.store.root)
        raw = git.run('log', f'--skip={offset}', f'-n{limit + 1}', '--format=%H%x09%an%x09%cI%x09%s')
        rows = [line.split('\t', 3) for line in raw.splitlines() if line]
        total = int(git.run('rev-list', '--count', 'HEAD') or 0)
        status = self.update_status()
        return {'entries': [{'sha': r[0], 'author': r[1], 'date': r[2], 'message': r[3]} for r in rows[:limit]],
                'total': total, 'hasMore': len(rows) > limit,
                'localHead': status['localHead'], 'upstreamHead': status['upstreamHead']}

    def update_action(self, action):
        updater = self.runtime.updater
        if updater is None:
            raise ApiError('UNSUPPORTED', '更新组件未初始化')
        if action == 'fetch':
            threading.Thread(target=updater.check, name='webui-update-check', daemon=True).start()
        elif action == 'apply':
            updater.install()
        else:
            raise ApiError('UNSUPPORTED', '源码更新开始后不能取消')
        return {'accepted': True}


def launcher_status():
    return {'connected': False, 'platform': '', 'version': '', 'capabilities': [],
            'autostart': {'supported': False, 'enabled': None}, 'commands': []}
