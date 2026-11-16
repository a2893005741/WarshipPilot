"""Scheduler: priority, first run, due times persisted across restarts."""
from datetime import datetime, timedelta, timezone
import json
import tempfile
import threading
from pathlib import Path
import unittest

from module.scheduler.controller import TaskController
from module.config.task_settings import TaskDraft, save_task
from module.config.config import Config


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
        self.serial, self.status = '127.0.0.1:16416', 'live'
        self.auto_connect_enabled, self.next_connect = True, 0
        self.wake = threading.Event()


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

    def test_pending_update_preserves_scheduler_and_defers_next_task(self):
        configure(self.root, 'expedition', enabled=True)
        c = Recording(self.runtime)
        c.scheduler = True
        c.update_pending = True
        c.save_due()
        c.schedule()
        self.assertEqual(c.started, [])
        self.assertTrue(Recording(self.runtime).scheduler)

    def test_corrupt_schedule_file_is_ignored(self):
        Config(self.root).save_section('Scheduler', {'NextRun': {'expedition': 'bad date'}})
        self.assertEqual(Recording(self.runtime).due, {})


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.runtime = Runtime(self.root)
        configure(self.root, 'expedition', enabled=True)

    def test_scheduler_switch_survives_restart(self):
        c = Recording(self.runtime)
        c.control('scheduler-start')
        self.assertTrue(Recording(self.runtime).scheduler)
        c.control('scheduler-stop')
        self.assertFalse(Recording(self.runtime).scheduler)

    def test_waits_for_device_instead_of_failing(self):
        c = Recording(self.runtime)
        c.scheduler = True
        self.runtime.serial, self.runtime.status = '', 'idle'
        c.schedule()
        self.assertEqual(c.started, [])
        self.assertTrue(c.scheduler)

    def test_failure_retries_then_stops_after_three(self):
        c = Recording(self.runtime)
        c.scheduler = True
        c.task_failed('expedition', 'boom')
        self.assertTrue(c.scheduler)
        self.assertGreater(datetime.fromisoformat(c.due['expedition']), datetime.now(timezone.utc))
        c.task_failed('expedition', 'boom')
        c.task_failed('expedition', 'boom')
        self.assertFalse(c.scheduler)


if __name__ == '__main__':
    unittest.main()
