import json
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        for folder in ("samples", "faults", "sessions"):
            (root / folder).mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root / "records.sqlite3", check_same_thread=False)
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

    def samples(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT metadata FROM samples ORDER BY time DESC LIMIT 1000")]

    def close(self):
        self.db.close()
