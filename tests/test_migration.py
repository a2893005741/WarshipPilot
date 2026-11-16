"""Migration preserves old files, WAL records, scheduler and existing new config."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from unittest.mock import patch

from module.config.config import Config
from module.config.migration import migrate, copy_missing
from module.logger import atomic_json
from module.config.task_settings import TaskDraft,save_task
from tests.test_scheduler import Recording,Runtime


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'WarshipPilot'
        self.old=self.root/'data'
        self.old.mkdir(parents=True)
        for name,value in {
            'config.json':{'serial':'127.0.0.1:16416','screenshot_method':'nemu_ipc','control_method':'ADB','host':'127.0.0.1','adb_path':'D:/MuMu/adb.exe'},
            'access.json':{'key':'original-key'},
            'task-drafts.json':{'expedition':{'enabled':True,'interval_minutes':90}},
            'scheduler.json':{'scheduler':True,'due':{'expedition':'2030-01-01T00:00:00+00:00'}},
        }.items():
            atomic_json(self.old/name,value)
        for name in ('faults/f/state.json','runs/r/screen.png','sessions/s/a.png','samples/p/screen.png'):
            p=self.old/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')

    def hashes(self):
        return {str(p.relative_to(self.old)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.old.rglob('*') if p.is_file()}

    def test_copies_state_and_keeps_source_unchanged(self):
        before=self.hashes()
        self.assertEqual(migrate(self.root),self.old)
        config=Config(self.root)
        self.assertEqual(config.section('Device')['serial'],'127.0.0.1:16416')
        self.assertTrue(config.section('Tasks')['expedition']['enabled'])
        self.assertEqual(config.deploy()['WebUI']['AccessCode'],'original-key')
        self.assertEqual(config.deploy()['WebUI']['Host'],'127.0.0.1')
        controller=Recording(Runtime(self.root))
        self.assertTrue(controller.scheduler)
        self.assertEqual(controller.due['expedition'],'2030-01-01T00:00:00+00:00')
        self.assertEqual((self.root/'log/error/f/state.json').read_bytes(),b'fixture')
        self.assertEqual((self.root/'screenshots/runs/r/screen.png').read_bytes(),b'fixture')
        self.assertEqual(before,self.hashes())

    def test_repeat_preserves_newer_configuration(self):
        migrate(self.root)
        config=Config(self.root)
        config.save_section('Device',{'serial':'new'})
        (self.root/'screenshots/runs/r/screen.png').write_bytes(b'new')
        self.assertIsNone(migrate(self.root))
        self.assertEqual(config.section('Device')['serial'],'new')
        self.assertEqual((self.root/'screenshots/runs/r/screen.png').read_bytes(),b'new')

    def test_existing_new_config_wins(self):
        Config(self.root).save_section('Device',{'serial':'new'})
        migrate(self.root)
        self.assertEqual(Config(self.root).section('Device')['serial'],'new')
        self.assertEqual(Config(self.root).deploy()['WebUI']['AccessCode'],'original-key')

    def test_external_old_directory(self):
        external=self.root.parent/'WarshipPilot-data'
        self.old.rename(external)
        self.assertEqual(migrate(self.root),external)
        self.assertEqual(Config(self.root).deploy()['WebUI']['AccessCode'],'original-key')

    def test_sqlite_backup_includes_wal(self):
        database=sqlite3.connect(self.old/'records.sqlite3')
        self.addCleanup(database.close)
        database.execute('pragma journal_mode=WAL')
        database.execute('create table events(message text)')
        database.execute("insert into events values('committed WAL record')")
        database.commit()
        migrate(self.root)
        with closing(sqlite3.connect(self.root/'log/records.sqlite3')) as copied:
            self.assertEqual(copied.execute('select message from events').fetchone()[0],'committed WAL record')

    def test_corrupt_legacy_config_does_not_create_new_config(self):
        (self.old/'scheduler.json').write_text('{bad')
        with self.assertRaises(ValueError):migrate(self.root)
        self.assertFalse(Config(self.root).instance_file.exists())
        self.assertFalse((self.root/'log/migration.json').exists())

    def test_failed_copy_is_retryable(self):
        source = self.old/'runs/r/screen.png'
        target = self.root/'screenshots/runs/r/screen.png'
        def interrupted(source, destination):
            destination.write_bytes(b'partial')
            raise OSError('interrupted copy')
        with patch('module.config.migration.shutil.copy2', side_effect=interrupted):
            with self.assertRaises(OSError):
                copy_missing(source, target)
        self.assertFalse(target.exists())
        copy_missing(source, target)
        self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_section_writes_do_not_drop_scheduler(self):
        migrate(self.root)
        def save_tasks():
            for _ in range(20):save_task(self.root,'expedition',TaskDraft(enabled=True))
        def save_device():
            for _ in range(20):Config(self.root).save_section('Device',{'serial':'changed'})
        threads=[threading.Thread(target=save_tasks),threading.Thread(target=save_device)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertTrue(Config(self.root).section('Scheduler')['Enable'])
        self.assertTrue(Config(self.root).section('Tasks')['expedition']['enabled'])

if __name__=='__main__':unittest.main()
