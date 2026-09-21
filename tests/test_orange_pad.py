import sys
import unittest
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from orange_pad import detect_orange_pad


def blank_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (35, 45, 60)
    return frame


class OrangePadDetectionTests(unittest.TestCase):
    def test_finds_center_of_large_orange_rectangle(self):
        frame = blank_frame()
        frame[160:280, 100:220] = (255, 120, 0)
        found = detect_orange_pad(frame)
        self.assertIsNotNone(found)
        self.assertEqual(found.center, (160, 220))
        self.assertEqual(found.bbox, (100, 160, 220, 280))

    def test_ignores_tiny_orange_speck(self):
        frame = blank_frame()
        frame[40:44, 60:64] = (255, 120, 0)
        self.assertIsNone(detect_orange_pad(frame))

    def test_selects_largest_orange_patch(self):
        frame = blank_frame()
        frame[80:128, 80:128] = (255, 120, 0)
        frame[240:360, 360:480] = (255, 120, 0)
        found = detect_orange_pad(frame)
        self.assertEqual(found.center, (420, 300))

    def test_rejects_red_yellow_and_thin_orange_stripe(self):
        frame = blank_frame()
        frame[20:100, 20:100] = (255, 0, 0)
        frame[120:200, 120:200] = (255, 255, 0)
        frame[260:276, 40:400] = (255, 120, 0)
        self.assertIsNone(detect_orange_pad(frame))

    def test_ignores_dim_brown_surface_seen_in_camera_preview(self):
        frame = blank_frame()
        frame[160:280, 100:220] = (86, 56, 45)
        self.assertIsNone(detect_orange_pad(frame))

    def test_finds_orange_pad_split_by_dark_crossed_straps(self):
        frame = blank_frame()
        frame[120:320, 300:500] = (255, 120, 0)
        for y in range(120, 320):
            dx = y - 120
            frame[y, 300 + dx - 6:300 + dx + 6] = (20, 20, 20)
            frame[y, 499 - dx - 6:499 - dx + 6] = (20, 20, 20)
        found = detect_orange_pad(frame)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found.center[0], 400, delta=8)
        self.assertAlmostEqual(found.center[1], 220, delta=8)


if __name__ == "__main__":
    unittest.main()
