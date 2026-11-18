"""Persist task settings; expose the effective fixed legacy C plan."""
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from module.config.config import Config

TASKS = ('expedition', 'campaign', 'exercise', 'reward', 'sortie', 'sortie_a', 'sortie_b', 'decisive', 'general', 'control')
EXECUTABLE = ['expedition', 'campaign', 'exercise', 'reward', 'sortie', 'decisive']
# Decisive-only originals that earlier releases showed on the 功能控制台 page.
DECISIVE_FROM_CONTROL = ('换票资源', '351', 'U96', 'U1206', '鹦鹉螺', 'U1405', '鲃鱼', '开局SL潜艇')


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    priority: int = Field(default=5, ge=1, le=10)
    start_time: str = Field(default='00:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    interval_minutes: int = Field(default=60, ge=1, le=10080)
    fleet: int = Field(default=1, ge=1, le=8)
    runs: int = Field(default=1, ge=1, le=9999)
    difficulty: Literal['normal', 'hard'] = 'normal'
    stage: str = Field(default='', max_length=20, pattern=r'^(?:[1-9]\d?-[1-9]\d?)?$')
    route: str = Field(default='', max_length=40, pattern=r'^[A-Za-z0-9αβγδ →,，-]*$')
    night_battle: Literal['never', 'always'] = 'never'
    repair: Literal['wait', 'quick'] = 'wait'
    save_screenshots: bool = True
    legacy: dict[str, Any] = Field(default_factory=dict)


class TaskSettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: Literal['expedition', 'campaign', 'exercise', 'reward', 'sortie', 'sortie_a', 'sortie_b', 'decisive', 'general', 'control']
    settings: TaskDraft


def read_tasks(root):
    from module.config.schema import schema
    saved = Config(root).section('Tasks')
    tasks = {}
    for task in TASKS:
        defaults = {field['key']: field['value']
                    for fields in schema()['args'][task].values()
                    for field in fields.values() if field['storage'] == 'task'}
        raw = saved.get(task, {})
        if any(group in raw for group in schema()['args'][task]):
            flattened = {'legacy': {}}
            for group, fields in schema()['args'][task].items():
                for name, field in fields.items():
                    if name not in raw.get(group, {}):
                        continue
                    value = raw[group][name]
                    if field['storage'] == 'task':
                        flattened[field['key']] = value
                    elif field['storage'] == 'legacy':
                        flattened['legacy'][field['key']] = value
            raw = flattened
        if task == 'decisive':
            earlier = saved.get('control', {}).get('Control', {})
            legacy = dict(raw.get('legacy', {}))
            for key in DECISIVE_FROM_CONTROL:
                if key in earlier and key not in legacy:
                    legacy[key] = earlier[key]
            raw = raw | {'legacy': legacy}
        tasks[task] = TaskDraft.model_validate(defaults | raw).model_dump()
    # v0.3 stored inert drafts. The executable release uses the user's selected C.
    tasks['sortie'].update(fleet=2,stage='6-1',route='α',night_battle='never',repair='quick')
    return tasks


def grouped_tasks(root, tasks):
    from module.config.schema import schema
    due = Config(root).section('Scheduler').get('NextRun', {})
    result = {}
    for task, settings in tasks.items():
        result[task] = {}
        for group, fields in schema()['args'][task].items():
            result[task][group] = {}
            for name, field in fields.items():
                storage = field['storage']
                value = settings.get(field.get('key'), field['value']) if storage == 'task' else settings['legacy'].get(field['key'], field['value']) if storage == 'legacy' else due.get(task, '') if storage == 'scheduler' else field['value']
                result[task][group][name] = value
    return result


def normalize_tasks(root):
    config = Config(root)
    with config.lock:
        grouped = grouped_tasks(root, read_tasks(root))
        if grouped != config.section('Tasks'):
            config.save_section('Tasks', grouped)


def save_task(root, task, settings):
    from module.config.schema import schema, validate_value
    if task not in TASKS:
        raise ValueError('任务不存在')
    allowed = {field['key']: field for fields in schema()['args'][task].values()
               for field in fields.values() if field['storage'] == 'legacy'}
    for key, value in settings.legacy.items():
        if key not in allowed:
            raise ValueError('该字段不属于此任务：' + key)
        field = allowed[key]
        validate_value(field, value)
        if field.get('display') == 'readonly' and value != field['value']:
            raise ValueError('该配置项只读：' + key)
    config = Config(root)
    with config.lock:
        tasks = read_tasks(root)
        tasks[task] = settings.model_dump()
        config.save_section('Tasks', grouped_tasks(root, tasks))
    return {'tasks': read_tasks(root), 'executable': True, 'supported': EXECUTABLE}
