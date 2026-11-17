"""Remembered expedition countdowns: keys of live chapter tiles, persistence."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from module.expedition import expedition as exp
from module.expedition.memory import FULL_EVERY, TimerMemory, chapter_key
from tests.test_expedition import live_tile

NOW = datetime(2026, 11, 17, 1, 0, tzinfo=timezone.utc)


def live_keys():
    return [chapter_key(live_tile(f'tile-ch{i}')) for i in range(1, 11)]


class MemoryTest(unittest.TestCase):
    def memory(self, path=None):
        memory = TimerMemory(path)
        walked = [(key, [3600 * i] if i in (2, 3) else [], 0) for i, key in enumerate(live_keys(), 1)]
        memory.rebuild(NOW, walked)
        return memory

    def test_recognises_every_live_chapter(self):
        memory = self.memory()
        for i in range(1, 11):
            self.assertEqual(memory.index_of(chapter_key(live_tile(f'tile-ch{i}'))), i - 1)
        self.assertEqual(memory.index_of(chapter_key(live_tile('tile-ch4b'))), 3)
        self.assertEqual(memory.index_of(chapter_key(live_tile('tile-ch9b'))), 8)

    def test_round_trip(self):
        path = Path(tempfile.mkdtemp()) / 'timers.json'
        self.memory(path).save()
        again = TimerMemory.load(path)
        self.assertEqual(again.surveyed, NOW)
        self.assertEqual(again.remaining(NOW + timedelta(minutes=30)), [5400, 9000])  # 2 h and 3 h fleets
        self.assertEqual(again.index_of(chapter_key(live_tile('tile-ch7'))), 6)

    def test_missing_or_corrupt_file_is_empty(self):
        folder = Path(tempfile.mkdtemp())
        (folder / 'bad.json').write_text('{', encoding='utf-8')
        for path in (folder / 'none.json', folder / 'bad.json'):
            self.assertFalse(TimerMemory.load(path).usable(NOW))

    def test_overdue_and_age(self):
        memory = self.memory()
        self.assertEqual(memory.overdue(NOW + timedelta(hours=2)), set())          # ends exactly now
        self.assertEqual(memory.overdue(NOW + timedelta(hours=2, minutes=1)), {1})  # chapter 2's fleet
        self.assertTrue(memory.usable(NOW + FULL_EVERY - timedelta(seconds=1)))
        self.assertFalse(memory.usable(NOW + FULL_EVERY))

    def test_update_replaces_one_chapter(self):
        memory = self.memory()
        memory.update(1, NOW + timedelta(minutes=10), [5400], 0)
        self.assertEqual(memory.remaining(NOW + timedelta(minutes=10)), [5400, 10200])


if __name__ == '__main__':
    unittest.main()
