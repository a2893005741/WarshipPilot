"""Remembered expedition countdowns, so a run re-reads only what changed.

The game does the chapter routing itself: with an expedition finished,
出征 opens 出征-远征 on that chapter, each collection jumps to the next
finished one in order, and the list finally stays on the chapter of the last
redeployed expedition. So after a run only the chapters collected on can
have new countdowns; the others keep the end times seen earlier.

A full walk of all chapters stores, per chapter in list order, a small
signature of its selected tile and the absolute end time of each fleet away.
The memory is not trusted (caller falls back to a full walk) when it is older
than FULL_EVERY, when a chapter cannot be recognised, or when a remembered
fleet should have returned but nothing was collected (e.g. the player
dispatched or cancelled an expedition by hand).

Stored as JSON in log/expedition-timers.json (a cache: losing it only costs
one full walk).
"""
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path

import cv2
import numpy as np

from module.logger import atomic_json

log = logging.getLogger('warship.expedition')

FULL_EVERY = timedelta(hours=12)
OVERDUE = timedelta(seconds=20)  # a fleet this far past its end must have been collected
KEY_W, KEY_H = 64, 16
KEY_MATCH = 6.0                  # mean grey difference of two keys of one chapter


def chapter_key(tile_signature):
    """Downscaled selected-chapter tile (see expedition.chapter_signature)."""
    tile = np.clip(tile_signature, 0, 255).astype(np.uint8)
    return cv2.resize(tile, (KEY_W, KEY_H), interpolation=cv2.INTER_AREA)


def key_distance(a, b):
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


@dataclass
class Chapter:
    key: np.ndarray
    ends: list = field(default_factory=list)   # aware datetimes
    unreadable: int = 0


class TimerMemory:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.surveyed = None
        self.chapters = []

    # --- persistence ----------------------------------------------------------
    @classmethod
    def load(cls, path):
        memory = cls(path)
        try:
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            memory.surveyed = datetime.fromisoformat(data['surveyed'])
            for item in data['chapters']:
                key = np.frombuffer(base64.b64decode(item['key']), np.uint8).reshape(KEY_H, KEY_W)
                memory.chapters.append(Chapter(key.copy(), [datetime.fromisoformat(e) for e in item['ends']],
                                               int(item.get('unreadable', 0))))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if Path(path).exists():
                log.warning('expedition timer memory ignored: %s', exc)
            memory.surveyed, memory.chapters = None, []
        return memory

    def save(self):
        if self.path is None or self.surveyed is None:
            return
        atomic_json(self.path, {
            'surveyed': self.surveyed.isoformat(),
            'chapters': [{'key': base64.b64encode(c.key.tobytes()).decode('ascii'),
                          'ends': [e.isoformat() for e in c.ends], 'unreadable': c.unreadable}
                         for c in self.chapters]})

    # --- queries ---------------------------------------------------------------
    def usable(self, now):
        return bool(self.chapters) and self.surveyed is not None and now - self.surveyed < FULL_EVERY

    def index_of(self, key):
        """Chapter index whose key matches, or None (unknown or ambiguous)."""
        scores = sorted((key_distance(key, c.key), i) for i, c in enumerate(self.chapters))
        if not scores or scores[0][0] >= KEY_MATCH:
            return None
        if len(scores) > 1 and scores[1][0] < KEY_MATCH:
            return None
        return scores[0][1]

    def overdue(self, now):
        """Chapters with a fleet that should already be back."""
        return {i for i, c in enumerate(self.chapters) for end in c.ends if end <= now - OVERDUE}

    def remaining(self, now):
        return sorted(max(0, int((end - now).total_seconds())) for c in self.chapters for end in c.ends)

    @property
    def unreadable(self):
        return sum(c.unreadable for c in self.chapters)

    def view(self, now):
        """[(seconds, unreadable)] per chapter, as ExpeditionResult.chapters."""
        return [(sorted(max(0, int((e - now).total_seconds())) for e in c.ends), c.unreadable)
                for c in self.chapters]

    # --- updates ---------------------------------------------------------------
    def rebuild(self, now, walked):
        """walked: [(key, seconds, unreadable)] for every chapter, first to last."""
        self.surveyed = now
        self.chapters = [Chapter(key, [now + timedelta(seconds=s) for s in seconds], missed)
                         for key, seconds, missed in walked]

    def update(self, index, now, seconds, unreadable):
        chapter = self.chapters[index]
        chapter.ends = [now + timedelta(seconds=s) for s in seconds]
        chapter.unreadable = unreadable
