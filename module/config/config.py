"""Installation-local configuration. Independent sections update atomically."""
from copy import deepcopy
import json
from pathlib import Path
import secrets
import threading

import yaml

from module.logger import atomic_json

_locks = {}
_registry_lock = threading.Lock()


def config_lock(root):
    with _registry_lock:
        return _locks.setdefault(str(Path(root).resolve()), threading.RLock())


def deploy_defaults():
    return {
        'Git': {'Executable': '.venv/git/cmd/git.exe', 'Repository': '',
                'Branch': 'main', 'Remote': 'origin', 'AutoUpdate': True},
        'Python': {'Executable': '.venv/Scripts/python.exe', 'Uv': '.venv/uv.exe'},
        'Adb': {'Executable': '.venv/adb/adb.exe'},
        'WebUI': {'Host': '0.0.0.0', 'Port': 22680, 'AccessCode': ''},
        'Update': {'AutoCheck': True},
    }


class Config:
    def __init__(self, root):
        self.root = Path(root)
        self.folder = self.root / 'config'
        self.instance_file = self.folder / 'warship.json'
        self.deploy_file = self.folder / 'deploy.yaml'
        self.lock = config_lock(self.root)

    def instance(self):
        with self.lock:
            if self.instance_file.exists():
                value = json.loads(self.instance_file.read_text(encoding='utf-8-sig'))
                if not isinstance(value, dict):
                    raise ValueError('warship.json 必须是 JSON 对象')
                return value
            template = Path(__file__).resolve().parents[2] / 'config/template.json'
            if template.exists():
                return json.loads(template.read_text(encoding='utf-8'))
            return {'schema_version': 2, 'Device': {}, 'Tasks': {},
                    'Scheduler': {'Enable': False, 'NextRun': {}}}

    def section(self, name):
        return deepcopy(self.instance().get(name, {}))

    def save_section(self, name, value):
        with self.lock:
            current = self.instance()
            current[name] = deepcopy(value)
            if name == 'Tasks' and any('Scheduler' in task for task in value.values()):
                current['schema_version'] = 2
            if name == 'Scheduler':
                for task, fields in current.get('Tasks', {}).items():
                    if 'Scheduler' in fields:
                        fields['Scheduler']['NextRun'] = value.get('NextRun', {}).get(task, '')
            atomic_json(self.instance_file, current)

    def deploy(self):
        with self.lock:
            value = deploy_defaults()
            for section, relative in (('Git', '.warship/tools/git/cmd/git.exe'), ('Adb', '.warship/tools/adb/adb.exe')):
                if (self.root / relative).is_file():
                    value[section]['Executable'] = relative
            if (self.root / '.venv/Scripts/uv.exe').is_file():
                value['Python']['Uv'] = '.venv/Scripts/uv.exe'
            if self.deploy_file.exists():
                saved = yaml.safe_load(self.deploy_file.read_text(encoding='utf-8-sig'))
                if not isinstance(saved, dict):
                    raise ValueError('deploy.yaml 必须是 YAML 对象')
                for key, section in saved.items():
                    if isinstance(section, dict) and isinstance(value.get(key), dict):
                        value[key].update(section)
                    else:
                        value[key] = section
            return value

    def save_deploy(self, value):
        from module.logger import atomic_text
        with self.lock:
            atomic_text(self.deploy_file, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def ensure(self):
        with self.lock:
            if not self.instance_file.exists():
                atomic_json(self.instance_file, self.instance())
            if not self.deploy_file.exists():
                value = self.deploy()
                value['WebUI']['AccessCode'] = secrets.token_urlsafe(24)
                self.save_deploy(value)
            elif not self.deploy()['WebUI']['AccessCode']:
                value = self.deploy()
                value['WebUI']['AccessCode'] = secrets.token_urlsafe(24)
                self.save_deploy(value)

    def executable(self, section, key='Executable'):
        path = Path(self.deploy()[section][key])
        return str(path if path.is_absolute() else self.root / path)
