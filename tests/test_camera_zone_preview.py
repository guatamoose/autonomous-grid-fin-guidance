import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from camera_zone_preview import (OverlayTelemetry, build_overlay_lines,
                                 overlay_zones)
from servo_controller import NEUTRAL


class PreviewTests(unittest.TestCase):
    def test_overlay_lines_include_lock_and_signed_servo_movements(self):
        telemetry = OverlayTelemetry(
            state="locked", acquire_count=3, requested_us=300,
            direction="left-up",
            pulses={7: 1705, 8: 1260, 9: 1570, 10: 1000},
            neutrals=NEUTRAL, observe_only=False, fps=12.4,
            recording="active", timestamp="2026-09-21T05:12:03Z")
        text = "\n".join(build_overlay_lines(telemetry))
        self.assertIn("LOCKED 3/3", text)
        self.assertIn("left-up", text)
        self.assertIn("request 300 us", text)
        self.assertIn("S7 1705 (+200)", text)
        self.assertIn("S10 1000 (-200)", text)
        self.assertIn("12.4 fps", text)
        self.assertIn("REC active", text)
        self.assertIn("2026-09-21T05:12:03Z", text)

    def test_observe_only_overlay_distinguishes_request_from_actual_neutral(self):
        telemetry = OverlayTelemetry(
            state="locked", acquire_count=3, requested_us=400,
            direction="right", pulses=dict(NEUTRAL), neutrals=NEUTRAL,
            observe_only=True, fps=11.0, recording="active",
            timestamp="2026-09-21T05:12:04Z")
        text = "\n".join(build_overlay_lines(telemetry))
        self.assertIn("request 400 us", text)
        self.assertIn("OBSERVE ONLY", text)
        self.assertIn("S7 1505 (+0)", text)

    def test_explicit_missing_detection_does_not_repeat_detection(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with patch("camera_zone_preview.detect_orange_pad",
                   side_effect=AssertionError("detector ran twice")):
            image = overlay_zones(frame, detection=None)
        self.assertEqual(image.size, (640, 480))


if __name__ == "__main__":
    unittest.main()
