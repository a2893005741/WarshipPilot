"""AzurPilot-style Duration OCR with OCR templates, on live timer crops.

Fixtures are the right-hand timer panels of 出征-远征 (x 1040-1250, y 100-680)
captured from the running game; they are pasted back at their position.
"""
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from module.expedition import timer
from module.ocr.ocr import Duration
from module.ocr.template import OcrTemplate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'expedition'


def panel(name):
    crop = cv2.imdecode(np.fromfile(FIXTURES / f'{name}.png', np.uint8), cv2.IMREAD_COLOR)
    image = np.full((720, 1280, 3), 30, np.uint8)
    image[100:680, 1040:1250] = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    return image


def seconds(h, m, s):
    return h * 3600 + m * 60 + s


def shipped_template():
    """Shipped glyphs, but learning goes to a temporary folder."""
    template = OcrTemplate('duration', '0123456789')
    template.learned = Path(tempfile.mkdtemp()) / 'duration.npz'
    return template


class TimerTest(unittest.TestCase):
    def test_running_countdowns_from_templates(self):
        cases = {'idle': [], 'mixed': [seconds(2, 57, 22)], 'single': [seconds(4, 56, 48)],
                 'ticking': [seconds(4, 58, 24)], 'short': [seconds(0, 59, 16)]}
        for name, expected in cases.items():
            with self.subTest(name):
                self.assertEqual(timer.running(panel(name), shipped_template()), (expected, 0))

    def test_row_states(self):
        gray = cv2.cvtColor(panel('mixed'), cv2.COLOR_RGB2GRAY)
        self.assertEqual([timer.row_state(gray, r) for r in range(4)], ['idle', 'idle', 'running', 'idle'])
        gray = cv2.cvtColor(panel('single'), cv2.COLOR_RGB2GRAY)
        self.assertEqual([timer.row_state(gray, r) for r in range(4)], ['running', 'none', 'none', 'none'])

    def test_template_answers_without_model(self):
        ocr = timer.reader([0], shipped_template())
        with mock.patch.object(type(ocr.cnocr), 'atomic_ocr_for_single_lines',
                               side_effect=AssertionError('model called')):
            self.assertEqual(ocr.ocr(panel('ticking')), timedelta(hours=4, minutes=58, seconds=24))
        self.assertEqual(ocr.sources, ['template'])


class ModelFallbackTest(unittest.TestCase):
    """No shipped glyphs: the ONNX model reads, the template learns."""

    def test_model_reads_and_template_learns(self):
        root = Path(tempfile.mkdtemp())
        template = OcrTemplate('duration', '0123456789', root=root)
        image = panel('ticking')
        first = timer.reader([0], template)
        self.assertEqual(first.ocr(image), timedelta(hours=4, minutes=58, seconds=24))
        self.assertEqual(first.sources, ['model'])
        self.assertTrue((root / 'log' / 'ocr' / 'duration.npz').exists())

        again = OcrTemplate('duration', '0123456789', root=root)  # reloads the learned glyphs
        second = timer.reader([0], again)
        self.assertEqual(second.ocr(image), timedelta(hours=4, minutes=58, seconds=24))
        self.assertEqual(second.sources, ['template'])

    def test_broken_model_leaves_area_unreadable(self):
        ocr = timer.reader([0], OcrTemplate('duration', '0123456789', root=tempfile.mkdtemp()))
        with mock.patch.object(type(ocr.cnocr), 'atomic_ocr_for_single_lines', side_effect=OSError('dll')):
            self.assertEqual(timer.running(panel('ticking'), ocr.template), ([], 1))

    def test_unreadable_area_is_not_zero(self):
        ocr = Duration((0, 0, 50, 20), letter=(51, 51, 51), template=shipped_template())
        value = ocr.ocr(np.full((720, 1280, 3), 242, np.uint8))
        self.assertEqual(value, timedelta(0))
        self.assertEqual(ocr.last_valid, [False])


if __name__ == '__main__':
    unittest.main()
