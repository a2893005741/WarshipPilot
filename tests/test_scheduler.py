"""Scheduler: priority, first run, due times persisted across restarts."""
from datetime import datetime, timedelta, timezone
import json
import tempfile
import threading
from pathlib import Path
import unittest

from backend.automation import TaskController
from backend.task_settings import TaskDraft, save_task


class Store:
    def __init__(self, root):
        self.root = root
        self.events = []

    def event(self, message, level='info'):
        self.events.append(message)


class Runtime:
    def __init__(self, root):
        self.store = Store(root)
        self.lock = threading.RLock()


class Recording(TaskController):
    def __init__(self, runtime):
        super().__init__(runtime)
        self.started = []

    def start(self, task):
        self.started.append(task)


def configure(root, task, **values):
    save_task(root, task, TaskDraft(**values))


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.runtime = Runtime(self.root)

    def test_off_by_default_and_runs_highest_priority_first(self):
        configure(self.root, 'expedition', enabled=True, priority=2)
        configure(self.root, 'sortie', enabled=True, priority=1)
        c = Recording(self.runtime)
        c.schedule()
        self.assertEqual(c.started, [])
        c.scheduler = True
        c.schedule()
        self.assertEqual(c.started, ['sortie'])

    def test_disabled_and_not_due_tasks_wait(self):
        configure(self.root, 'expedition', enabled=True)
        c = Recording(self.runtime)
        c.scheduler = True
        c.due['expedition'] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        c.schedule()
        self.assertEqual(c.started, [])
        c.due['expedition'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        c.schedule()
        self.assertEqual(c.started, ['expedition'])

    def test_due_times_survive_restart(self):
        c = Recording(self.runtime)
        c.due['expedition'] = '2030-01-01T00:00:00+00:00'
        c.save_due()
        again = Recording(self.runtime)
        self.assertEqual(again.due, {'expedition': '2030-01-01T00:00:00+00:00'})

    def test_corrupt_schedule_file_is_ignored(self):
        (self.root / 'scheduler.json').write_text('{bad', encoding='utf-8')
        self.assertEqual(Recording(self.runtime).due, {})


if __name__ == '__main__':
    unittest.main()
