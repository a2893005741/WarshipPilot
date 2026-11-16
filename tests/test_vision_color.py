"""Original-engine colour semantics and generated page rules."""
import glob
import json
from pathlib import Path
import unittest

import numpy as np

from backend.vision import color
from backend.ui.pages import Frame, PageDetector

ROOT = Path(__file__).resolve().parents[1]


def frame_with(x, y, rgb):
    image = np.zeros((720, 1280, 3), np.uint8)
    X, Y = color.to_screen(x, y)
    image[Y, X] = rgb
    return image


class ThresholdTest(unittest.TestCase):
    # Cases from 项目解析/深入分析/02-识别接口.md (native L1 rule vs per-channel).
    def test_threshold_constant(self):
        self.assertEqual(color.threshold(0.9), 76)
        self.assertEqual(color.threshold(0.999), 0)
        self.assertEqual(color.threshold(1.0), 0)

    def test_l1_sum_not_per_channel(self):
        expected = '646464'  # BBGGRR grey 100
        self.assertTrue(color.cmp_points(frame_with(10, 10, (140, 100, 100)), f'10|10|{expected}', 0.9))
        self.assertFalse(color.cmp_points(frame_with(10, 10, (127, 127, 127)), f'10|10|{expected}', 0.9))
        self.assertFalse(color.cmp_points(frame_with(10, 10, (101, 100, 100)), f'10|10|{expected}', 1.0))

    def test_explicit_deviation_per_channel(self):
        image = frame_with(5, 5, (0x7F, 0x7F, 0x7F))  # 0x80 below FFFFFF on every channel
        self.assertTrue(color.cmp_points(image, '5|5|FFFFFF-808080', 1.0))
        self.assertFalse(color.cmp_points(image, '5|5|FFFFFF-7F7F7F', 1.0))

    def test_bgr_order_and_alternatives(self):
        image = frame_with(1, 2, (0xFF, 0x00, 0x00))  # pure red
        self.assertEqual(color.cmp_color(image, 1, 2, '0000FF', 1.0), 0)
        self.assertEqual(color.cmp_color(image, 1, 2, 'FF0000', 1.0), -1)
        self.assertEqual(color.cmp_color(image, 1, 2, '00FF00|0000FF', 1.0), 1)


class GeometryTest(unittest.TestCase):
    def test_corners(self):
        self.assertEqual(color.to_screen(0, 0), (0, 719))
        self.assertEqual(color.to_screen(539, 0), (0, 0))
        self.assertEqual(color.to_screen(0, 959), (1279, 719))
        self.assertEqual(color.to_screen(539, 959), (1279, 0))

    def test_floor_half_up(self):
        # 1.5 * 4/3 = 2.0 exactly; 0.375 * 4/3 = 0.5 rounds up (not to even).
        self.assertEqual(color.to_screen(0, 0.375)[0], 1)

    def test_region_and_point_sample_identically(self):
        image = frame_with(539, 959, (1, 2, 3))
        view = color.portrait_view(image)
        self.assertEqual(tuple(view[959, 539]), (1, 2, 3))
        self.assertEqual(tuple(color.pixel(image, 539, 959)), (1, 2, 3))


class FindDirectionTest(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((720, 1280, 3), np.uint8)
        for x, y in ((10, 10), (30, 10), (10, 30), (30, 30), (20, 20)):
            X, Y = color.to_screen(x, y)
            self.image[Y, X] = (255, 255, 255)

    def find(self, direction):
        return color.find_multi_color(self.image, 0, 0, 40, 40, 'FFFFFF', '', direction, 1.0)

    def test_directions(self):
        self.assertEqual(self.find(0), (10, 10))
        self.assertEqual(self.find(1), (20, 20))
        self.assertEqual(self.find(2), (30, 30))
        self.assertEqual(self.find(3), (10, 30))
        self.assertEqual(self.find(4), (30, 10))
        self.assertEqual(self.find(7), (10, 30))

    def test_reversed_and_full_canvas_ranges(self):
        self.assertEqual(color.find_multi_color(self.image, 40, 40, 0, 0, 'FFFFFF', '', 0, 1.0), (10, 10))
        self.assertEqual(color.find_multi_color(self.image, 0, 0, 0, 0, 'FFFFFF', '', 0, 1.0), (10, 10))

    def test_offsets(self):
        self.assertEqual(color.find_multi_color(self.image, 0, 0, 40, 40, 'FFFFFF', '10|10|FFFFFF', 0, 1.0), (10, 10))
        self.assertEqual(color.find_multi_color(self.image, 0, 0, 40, 40, 'FFFFFF', '5|0|FFFFFF', 0, 1.0), (-1, -1))


class GeneratedPagesTest(unittest.TestCase):
    def setUp(self):
        self.pages = json.loads((ROOT / 'assets/pages.json').read_text(encoding='utf-8'))

    def test_generation_replayed_cleanly(self):
        self.assertEqual(self.pages['replay']['mismatches'], {})
        self.assertIsNone(self.pages['replay']['cycle'])
        self.assertEqual(len({p['name'] for p in self.pages['pages']}), 101)

    def test_blank_frame_is_unknown(self):
        self.assertIsNone(PageDetector(ROOT / 'assets/pages.json').detect(np.zeros((720, 1280, 3), np.uint8)))

    @unittest.skipUnless(glob.glob(str(ROOT / 'evidence/*.png')), 'local evidence frames not present')
    def test_recorded_frames_match_original(self):
        import cv2
        report = json.loads((ROOT / 'tools/legacy_extract/validation.json').read_text(encoding='utf-8'))
        detector = PageDetector(ROOT / 'assets/pages.json')
        for item in report['results']:
            path = ROOT / item['file']
            if not path.exists():
                continue
            image = cv2.cvtColor(cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            with self.subTest(frame=item['file']):
                self.assertEqual(detector.detect(Frame(image)), item['original'])


if __name__ == '__main__':
    unittest.main()
