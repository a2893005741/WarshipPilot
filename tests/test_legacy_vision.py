"""Small regression checks for coordinate/color mistakes that would misread a game frame."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from module.vision.legacy import ColorProfile, LegacyVision


class ColorRulesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        points = [{"x": 4, "y": 7, "colors": [{"hex": "112233", "tolerance_hex": "010203"}, {"hex": "ABCDEF", "tolerance_hex": None}]},
                  {"x": 6, "y": 9, "colors": [{"hex": "445566", "tolerance_hex": None}]},
                  {"x": 9, "y": 12, "colors": [{"hex": "778899", "tolerance_hex": None}]}]
        rule = {"id": "sample", "kind": "points", "point_count": 3, "context_hints": [], "points": points}
        catalog = {"point_expressions": [rule], "color_groups": [], "needs_review": []}
        Path(self.folder.name, "rules.json").write_text(json.dumps(catalog), encoding="utf-8")
        self.vision = LegacyVision(Path(self.folder.name))

    def tearDown(self):
        self.folder.cleanup()

    def test_rotation_corners_preserve_orientation(self):
        expected = {0: [(0,0),(39,0),(0,19)], 90: [(19,0),(19,39),(0,0)],
                    180: [(39,19),(0,19),(39,0)], 270: [(0,39),(0,0),(19,39)]}
        for rotation, corners in expected.items():
            width, height = (20,40) if rotation in (90,270) else (40,20)
            transform = LegacyVision.mapping(ColorProfile(base_width=40,base_height=20,rotation=rotation),width,height)
            self.assertEqual([transform(0,0),transform(39,0),transform(0,19)],corners)

    def test_color_candidates_and_bgr_tolerance(self):
        image = np.zeros((20,40,3),dtype=np.uint8)
        image[7,4] = [0xEF,0xCD,0xAB]  # Match the second BGR candidate.
        image[9,6] = [0x66,0x55,0x44]
        image[12,9] = [0x99,0x88,0x77]
        profile = ColorProfile(base_width=40,base_height=20,rotation=0,color_order="BGR",tolerance=0)
        self.assertTrue(self.vision.evaluate(image,"sample",profile)["matched"])
        self.assertFalse(self.vision.evaluate(image,"sample",profile.model_copy(update={"color_order":"RGB"}))["matched"])
        image[7,4] = [0x36,0x24,0x12]  # Embedded tolerance is reversed along with BGR.
        self.assertTrue(self.vision.evaluate(image,"sample",profile)["matched"])
        image[7,4,0] += 1
        self.assertFalse(self.vision.evaluate(image,"sample",profile)["matched"])

    def test_relative_anchor_applies_after_rotation(self):
        profile = ColorProfile(base_width=40,base_height=20,rotation=270,mode="relative",anchor_x=12,anchor_y=30)
        transform = LegacyVision.mapping(profile,20,40)
        self.assertEqual(transform(-3,2),(14,33))

    def test_outside_point_never_becomes_partial_success(self):
        profile = ColorProfile(base_width=40,base_height=20,rotation=0,mode="relative",anchor_x=38,anchor_y=18)
        result = self.vision.evaluate(np.full((20,40,3),255,dtype=np.uint8),"sample",profile)
        self.assertEqual(result["status"],"out_of_bounds")
        self.assertEqual(result["outside_points"],3)
        self.assertFalse(result["matched"])
        self.assertEqual(self.vision.scan(np.zeros((20,40,3),dtype=np.uint8),profile)["evaluated_rules"],0)

    def test_incompatible_aspect_ratio_is_rejected(self):
        with self.assertRaises(ValueError):
            LegacyVision.mapping(ColorProfile(),1280,800)


if __name__ == "__main__":
    unittest.main()
