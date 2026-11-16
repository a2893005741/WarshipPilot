"""Copy old 0.5.x state without writing to the source installation."""
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing

from module.config.config import Config
from module.logger import atomic_json, now


def read_object(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'旧配置不是 JSON 对象：{path}')
    return value


def copy_missing(source, target):
    if not source.exists():
        return
    if source.is_dir():
        for file in source.rglob('*'):
            if file.is_file():
                copy_missing(file, target / file.relative_to(source))
    elif not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def migrate(root, sources=None):
    root = Path(root)
    config = Config(root)
    marker = root / 'log' / 'migration.json'
    with config.lock:
        if marker.exists():
            config.ensure()
            return None
        sources = sources if sources is not None else [root / 'data', root.parent / 'WarshipPilot-data']
        source = next((Path(s) for s in sources if any((Path(s) / f).exists()
                      for f in ('config.json', 'access.json', 'scheduler.json', 'records.sqlite3'))), None)
        if source is None:
            config.ensure()
            return None
        # Parse before copying or committing configuration; corrupt legacy state is visible.
        old = read_object(source / 'config.json')
        access = read_object(source / 'access.json')
        tasks = read_object(source / 'task-drafts.json')
        scheduler = read_object(source / 'scheduler.json')
        deployment = config.deploy()
        instance = config.instance()
        if not config.instance_file.exists():
            instance.update(Device={k: v for k, v in old.items() if k not in ('host', 'adb_path')},
                            Tasks=tasks, Scheduler={'Enable': bool(scheduler.get('scheduler', False)),
                                                   'NextRun': scheduler.get('due', {})})
        if not config.deploy_file.exists():
            deployment['WebUI'].update(Host=old.get('host', '0.0.0.0'), AccessCode=access.get('key', ''))
            if old.get('adb_path'):
                deployment['Adb']['Executable'] = old['adb_path']
            if not deployment['WebUI']['AccessCode']:
                import secrets
                deployment['WebUI']['AccessCode'] = secrets.token_urlsafe(24)
        for old_name, new_name in (
            ('faults', 'log/error'), ('runs', 'screenshots/runs'),
            ('sessions', 'screenshots/sessions'), ('samples', 'screenshots/samples'),
            ('automation-last-run.json', 'log/automation-last-run.json'),
            ('legacy-files', 'log/legacy-files'),
        ):
            copy_missing(source / old_name, root / new_name)
        database = source / 'records.sqlite3'
        target = root / 'log' / 'records.sqlite3'
        if database.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # SQLite backup includes committed WAL pages; source stays read-only.
            temporary = target.with_suffix('.migrating')
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as src:
                with closing(sqlite3.connect(temporary)) as dst:
                    src.backup(dst)
            temporary.replace(target)
        if not config.instance_file.exists():
            atomic_json(config.instance_file, instance)
        if not config.deploy_file.exists():
            config.save_deploy(deployment)
        atomic_json(marker, {'source': str(source.resolve()), 'completed': now()})
        return source
