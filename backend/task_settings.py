"""Persist task settings; expose the effective fixed legacy C plan."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .store import atomic_json

TASKS = ('expedition', 'campaign', 'exercise', 'sortie')


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


class TaskSettingsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task: Literal['expedition', 'campaign', 'exercise', 'sortie']
    settings: TaskDraft


def read_tasks(root):
    path = root / 'task-drafts.json'
    saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    tasks = {task: TaskDraft.model_validate(saved.get(task, {})).model_dump() for task in TASKS}
    # v0.3 stored inert drafts. The executable release uses the user's selected C.
    tasks['sortie'].update(fleet=2,stage='6-1',route='α',night_battle='never',repair='quick')
    return tasks


def save_task(root, task, settings):
    tasks = read_tasks(root)
    tasks[task] = settings.model_dump()
    atomic_json(root / 'task-drafts.json', tasks)
    return {'tasks': read_tasks(root), 'executable': True, 'supported': ['expedition','sortie']}
