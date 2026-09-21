import importlib.util
import math
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "camera_zones.py"


def load_module():
    if not MODULE_PATH.exists():
        raise AssertionError("camera_zones.py has not been implemented")
    spec = importlib.util.spec_from_file_location("camera_zones", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CameraZoneTests(unittest.TestCase):
    def setUp(self):
        self.zones = load_module()

    def test_center_and_five_percent_dead_zone_request_no_movement(self):
        for x in (320, 330, 332):
            decision = self.zones.decide((x, 240), (640, 480))
            self.assertEqual(decision.requested_us, 0)
            self.assertEqual(decision.safe_us, 0)

    def test_concentric_radius_thresholds(self):
        # The center-to-nearest-edge radius is 240 pixels.
        cases = ((333, 100), (380, 100), (381, 200),
                 (440, 200), (441, 300), (500, 300), (501, 400))
        for x, expected in cases:
            with self.subTest(x=x):
                decision = self.zones.decide((x, 240), (640, 480))
                self.assertEqual(decision.requested_us, expected)

    def test_diagonal_target_splits_movement_between_axes(self):
        decision = self.zones.decide((400, 160), (640, 480))
        self.assertEqual(decision.requested_us, 200)
        self.assertAlmostEqual(decision.nose_x_us, math.sqrt(0.5) * 200)
        self.assertAlmostEqual(decision.nose_y_us, math.sqrt(0.5) * 200)

    def test_outer_ring_keeps_requested_400_but_caps_unverified_output(self):
        decision = self.zones.decide((540, 240), (640, 480))
        self.assertEqual(decision.requested_us, 400)
        self.assertEqual(decision.safe_us, 200)
        self.assertEqual(decision.safe_nose_x_us, 200)

    def test_no_target_requests_neutral(self):
        decision = self.zones.decide(None, (640, 480))
        self.assertEqual(decision.requested_us, 0)
        self.assertEqual(decision.safe_us, 0)
        self.assertFalse(decision.target_seen)

    def test_outside_frame_rejects_detection(self):
        with self.assertRaises(ValueError):
            self.zones.decide((-1, 240), (640, 480))


if __name__ == "__main__":
    unittest.main()
