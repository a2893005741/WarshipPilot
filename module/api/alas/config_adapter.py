"""WarshipPilot's ALAS-style task schema in the exact shape AzurPilot's WebUI reads.

WarshipPilot keeps labels on each field (name / help / {value, label} options);
AzurPilot's frontend expects ``args`` with raw option values and a separate
``translations`` tree keyed Group.Arg (plus Menu.* and Task.*). Where one
group's field is worded differently per task, the task's wording goes to
``translations.TaskArgs[task]`` (read first by the WebUI task page).

Reads and writes go through module.config.schema (validation and storage are
unchanged); this module only converts shapes and datetimes.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from functools import lru_cache

from module.api.alas.protocol import ApiError
from module.config.config import Config
from module.config.schema import config_values, save_field, schema

TIME_PATTERN = r'^([01]\d|2[0-3]):[0-5]\d$'
DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
RUN_NOW = '2020-01-01 00:00:00'  # AzurPilot: clearing NextRun means "run now"


def convert_field(field):
    """One WarshipPilot field definition -> AzurPilot Field."""
    kind = field['type']
    value = field.get('value')
    if kind == 'checkbox':
        out = {'type': 'checkbox', 'value': bool(value), 'option': [True, False]}
    elif kind == 'select':
        out = {'type': 'select', 'value': value, 'option': [option['value'] for option in field.get('option', [])]}
    elif kind == 'number':
        out = {'type': 'input', 'valuetype': 'int', 'value': value}
        if 'min' in field and 'max' in field:
            out['validate'] = [field['min'], field['max']]
    elif kind == 'time':
        out = {'type': 'input', 'valuetype': 'str', 'value': value, 'validate': TIME_PATTERN}
    elif kind == 'datetime-local':
        out = {'type': 'datetime', 'value': '', 'validate': 'datetime', 'preserve_empty': True}
    elif kind == 'textarea':
        out = {'type': 'textarea', 'valuetype': 'str', 'value': value}
    else:
        out = {'type': 'input', 'valuetype': 'str', 'value': value}
    if field.get('display') == 'readonly' or field.get('storage') == 'constant':
        out['display'] = 'disabled'
    return out


def field_text(field):
    text = {'name': field.get('name', ''), 'help': field.get('help', '')}
    for option in field.get('option', []):
        text[str(option['value'])] = option['label']
    if field['type'] == 'checkbox':
        text.update({'True': '开启', 'False': '关闭'})
    return text


@lru_cache(maxsize=1)
def alas_schema():
    """{'menu', 'args', 'translations'} for schema.get (language-independent:
    the original script's options only exist in Chinese)."""
    source = schema()
    menu, args = {}, {}
    translations = {'Menu': {}, 'Task': {}, 'TaskArgs': {},
                    # Settings page group titles (WarshipService.SETTINGS keys).
                    'Gui': {'DeploySetting': {'GroupWebUI': '控制台', 'GroupGit': '源码更新', 'GroupUpdate': '检查更新'}}}
    translations['Gui']['Launcher'] = {
        'Loading': '正在读取启动器状态', 'RemoteUnavailable': '远程连接无法设置本机启动器',
        'Unsupported': '当前启动器不支持开机自启', 'Disconnected': '启动器未连接',
        'Setting': '正在设置', 'Failed': '设置失败', 'Enabled': '开机自启已开启',
        'Disabled': '开机自启已关闭', 'Connected': '启动器已连接', 'StartupTitle': '启动器',
        'AutoStart': '开机自启', 'AutoStartHelp': '登录 Windows 后启动，并最小化到托盘。'}
    for key, item in source['menu'].items():
        menu[key] = {'menu': 'collapse', 'page': 'setting', 'tasks': list(item['tasks'])}
        translations['Menu'][key] = {'name': item['name'], 'help': ''}
    for task, info in source['tasks'].items():
        translations['Task'][task] = {'name': info['name'], 'help': info.get('help', '')}
    for task, groups in source['args'].items():
        args[task] = {}
        for group, fields in groups.items():
            args[task][group] = {}
            shared = translations.setdefault(group, {'_info': {'name': source['groups'].get(group, group), 'help': ''}})
            for arg, field in fields.items():
                args[task][group][arg] = convert_field(field)
                text = field_text(field)
                if arg not in shared:
                    shared[arg] = text
                elif shared[arg] != text:
                    translations['TaskArgs'].setdefault(task, {}).setdefault(group, {})[arg] = text
    return {'menu': menu, 'args': args, 'translations': translations}


def find_field(path):
    try:
        task, group, arg = path.split('.')
        return task, schema()['args'][task][group][arg]
    except (ValueError, KeyError):
        raise ApiError('NOT_FOUND', f'参数不存在：{path}')


def to_local_text(value):
    """Stored ISO time -> 'YYYY-MM-DD HH:MM:SS' local, '' when unset."""
    if not value:
        return ''
    try:
        return datetime.fromisoformat(value).astimezone().strftime(DATETIME_FORMAT)
    except ValueError:
        return ''


def from_local_text(value):
    if value in ('', RUN_NOW):
        return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    try:
        return datetime.strptime(value, DATETIME_FORMAT).astimezone().isoformat()
    except (TypeError, ValueError):
        raise ApiError('INVALID_PARAMS', '日期格式应为 YYYY-MM-DD HH:mm:ss')


class ConfigAdapter:
    """config.get / config.patch / config.export for the single instance."""

    def __init__(self, runtime, instance):
        self.runtime, self.instance = runtime, instance

    @property
    def root(self):
        return self.runtime.store.root

    def revision(self):
        file = Config(self.root).instance_file
        return hashlib.sha256(file.read_bytes() if file.exists() else b'').hexdigest()

    def values(self):
        values = {}
        for task, groups in schema()['args'].items():
            current = config_values(self.root, task)['values']
            values[task] = {}
            for group, fields in groups.items():
                values[task][group] = {}
                for arg, field in fields.items():
                    value = current.get(group, {}).get(arg, field.get('value'))
                    if field['type'] == 'datetime-local':
                        value = to_local_text(value)
                    values[task][group][arg] = value
        return values

    def get(self):
        return {'instance': self.instance, 'revision': self.revision(), 'values': self.values(), 'options': {}}

    def export(self):
        return self.values()

    def patch(self, revision, changes):
        seen = set()
        for change in changes:
            if change.path in seen:
                raise ApiError('INVALID_PARAMS', '同一次保存不能重复修改同一个参数')
            seen.add(change.path)
            _, field = find_field(change.path)
            if field.get('display') == 'readonly' or field.get('storage') == 'constant':
                raise ApiError('READ_ONLY', f'不允许修改只读参数：{change.path}')
        runtime = self.runtime
        for change in changes:
            _, field = find_field(change.path)
            value = change.value
            if field['type'] == 'datetime-local':
                value = from_local_text(value)
            elif field['type'] == 'number' and isinstance(value, str) and value.strip().lstrip('-').isdigit():
                value = int(value.strip())
            with runtime.lock:
                save_field(self.root, change.path, value)
                if change.path.endswith('.Scheduler.NextRun'):
                    runtime.automation.due = Config(self.root).section('Scheduler').get('NextRun', {})
        runtime.wake.set()
        return self.get()

    def run_now(self, task):
        """AzurPilot tasks.runNow: due now, picked by the running scheduler."""
        if task not in schema()['args'] or 'NextRun' not in schema()['args'][task].get('Scheduler', {}):
            raise ApiError('NOT_FOUND', f'任务不存在：{task}')
        from module.api.alas.protocol import ConfigChange
        return self.patch(None, [ConfigChange(path=f'{task}.Scheduler.NextRun', value=RUN_NOW)])


def search(query):
    """search.content over task names, group names and field labels."""
    data = alas_schema()
    needle = query.lower()
    tasks, groups, options = [], [], []
    seen_groups = set()
    for task, task_groups in data['args'].items():
        task_text = data['translations']['Task'][task]
        if needle in task_text['name'].lower():
            tasks.append({'task': task, 'key': task, 'label': task_text['name'], 'help': task_text['help'], 'values': ''})
        for group, fields in task_groups.items():
            info = data['translations'].get(group, {}).get('_info', {})
            if group not in seen_groups and needle in info.get('name', '').lower():
                seen_groups.add(group)
                groups.append({'task': task, 'key': group, 'label': info['name'], 'help': '', 'values': ''})
            for arg in fields:
                text = data['translations']['TaskArgs'].get(task, {}).get(group, {}).get(arg) \
                    or data['translations'][group][arg]
                if needle in text['name'].lower() or needle in arg.lower():
                    options.append({'task': task, 'key': f'{group}.{arg}', 'label': text['name'],
                                    'help': text['help'], 'values': ''})
    return {'tasks': tasks[:20], 'groups': groups[:20], 'options': options[:50]}


def copy_schema():
    return deepcopy(alas_schema())
