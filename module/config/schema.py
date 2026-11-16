"""Validate and persist task/group/argument paths against the generated schema."""
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path

from module.config.config import Config


@lru_cache(maxsize=1)
def schema():
    return json.loads((Path(__file__).parent / 'argument/schema.json').read_text(encoding='utf-8'))


def validate_value(field, value):
    kind = field['type']
    if kind == 'checkbox':
        valid = type(value) is bool
    elif kind in ('number', 'select'):
        valid = type(value) is int
    else:
        valid = isinstance(value, str) and len(value) <= 1000
    if not valid:
        raise ValueError('参数类型不正确：' + field['name'])
    if 'option' in field and value not in [option['value'] for option in field['option']]:
        raise ValueError('选项不在原脚本定义中：' + field['name'])
    if kind == 'number' and not field.get('min', -100000000) <= value <= field.get('max', 100000000):
        raise ValueError('数值超出范围：' + field['name'])
    if kind == 'time':
        datetime.strptime(value, '%H:%M')
    if kind == 'datetime-local' and value:
        datetime.fromisoformat(value)
    return value


def config_values(root, task):
    from module.config.task_settings import read_tasks
    if task not in schema()['tasks']:
        raise ValueError('任务不存在')
    settings = read_tasks(root)[task]
    due = Config(root).section('Scheduler').get('NextRun', {}).get(task, '')
    values = {}
    for group, fields in schema()['args'][task].items():
        values[group] = {}
        for name, field in fields.items():
            storage = field['storage']
            value = settings.get(field.get('key'), field['value']) if storage == 'task' else settings['legacy'].get(field['key'], field['value']) if storage == 'legacy' else due if storage == 'scheduler' else field['value']
            values[group][name] = value
    return {'task': task, 'values': values}


def save_field(root, path, value):
    from module.config.task_settings import TaskDraft, read_tasks, save_task
    try:
        task, group, name = path.split('.', 2)
        field = schema()['args'][task][group][name]
    except (ValueError, KeyError):
        raise ValueError('配置项不存在')
    if field.get('display') == 'readonly':
        raise ValueError('该配置项只读')
    validate_value(field, value)
    config = Config(root)
    with config.lock:
        if field['storage'] == 'scheduler':
            scheduler = config.section('Scheduler')
            due = scheduler.setdefault('NextRun', {})
            if value:
                moment = datetime.fromisoformat(value)
                due[task] = moment.astimezone().isoformat()
            else:
                due.pop(task, None)
            config.save_section('Scheduler', scheduler)
        else:
            settings = read_tasks(root)[task]
            if field['storage'] == 'legacy':
                settings['legacy'][field['key']] = value
            else:
                settings[field['key']] = value
            save_task(root, task, TaskDraft.model_validate(settings))
    return config_values(root, task)
