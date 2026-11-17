import json
import logging
from pathlib import Path
import sqlite3
import threading
import os
import tempfile
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def atomic_text(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for folder in ('log/error', 'screenshots/samples', 'screenshots/sessions', 'screenshots/runs'):
            (root / folder).mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / 'log' / "records.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT, level TEXT, message TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS samples (id TEXT PRIMARY KEY, time TEXT, label TEXT, metadata TEXT)")
        self.db.commit()

    def event(self, message: str, level="info"):
        with self.lock:
            self.db.execute("INSERT INTO events(time,level,message) VALUES(?,?,?)", (now(), level, message))
            self.db.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-5000 FROM events)")
            self.db.commit()

    def events(self):
        with self.lock:
            return [dict(zip(("id", "time", "level", "message"), row)) for row in
                    self.db.execute("SELECT id,time,level,message FROM events ORDER BY id DESC LIMIT 120")]

    def events_after(self, after: int, limit: int = 500):
        """Events with id > after, oldest first (WebUI log cursor), and the newest id."""
        with self.lock:
            newest = self.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            if after > newest:
                after = 0  # the store was reset; send the tail again
            rows = self.db.execute("SELECT id,time,level,message FROM (SELECT * FROM events WHERE id > ? "
                                   "ORDER BY id DESC LIMIT ?) ORDER BY id", (after, limit)).fetchall()
            return [dict(zip(("id", "time", "level", "message"), row)) for row in rows], newest

    def latest_event_id(self):
        with self.lock:
            return self.db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]

    def samples(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT metadata FROM samples ORDER BY time DESC LIMIT 1000")]

    def close(self):
        self.db.close()


_log = logging.getLogger("warship.device")

class _Logger:
    """AzurPilot logger surface: info/warning/... plus attr() and hr()."""

    def __getattr__(self, name):
        return getattr(_log, name)

    @staticmethod
    def attr(name, text):
        _log.info('[%s] %s', name, text)

    @staticmethod
    def hr(title, level=3):
        _log.info('==== %s ====', title)


logger = _Logger()
