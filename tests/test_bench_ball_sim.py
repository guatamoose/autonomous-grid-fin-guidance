import importlib.util
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from camera_zones import decide


def load_simulator():
    path = SRC / "bench_ball_sim.py"
    if not path.exists():
        raise AssertionError("bench_ball_sim.py has not been implemented")
    spec = importlib.util.spec_from_file_location("bench_ball_sim", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BenchBallSimulationTests(unittest.TestCase):
    def setUp(self):
        self.sim = load_simulator()

    def test_left_target_uses_the_recorded_opposite_pair(self):
        decision = decide((200, 240), (640, 480))
        self.assertEqual(self.sim.pulses_for(decision),
                         {7: 1505, 8: 1630, 9: 1400, 10: 1400})

    def test_up_target_uses_the_recorded_side_pair(self):
        decision = decide((320, 120), (640, 480))
        self.assertEqual(self.sim.pulses_for(decision),
                         {7: 1705, 8: 1430, 9: 1600, 10: 1200})

    def test_outer_ring_still_caps_real_bench_offset_at_200(self):
        decision = decide((600, 240), (640, 480))
        self.assertEqual(decision.requested_us, 400)
        self.assertEqual(self.sim.pulses_for(decision),
                         {7: 1505, 8: 1230, 9: 1800, 10: 1400})

    def test_invalid_controller_limits_block_movement(self):
        settings = self.sim.expected_settings()
        settings[9]["min"] = 1300
        with self.assertRaises(ValueError):
            self.sim.validate_settings(settings)

    def test_300_left_pair_uses_full_requested_offset(self):
        decision = decide((0, 240), (640, 480), max_tested_us=300)
        self.assertEqual(self.sim.bounded_pulses_for(
            decision, self.sim.expected_settings()),
            {7: 1505, 8: 1730, 9: 1300, 10: 1400})

    def test_400_up_pair_reaches_tested_endpoints(self):
        decision = decide((320, 0), (640, 480), max_tested_us=400)
        self.assertEqual(self.sim.bounded_pulses_for(
            decision, self.sim.expected_settings()),
            {7: 1905, 8: 1430, 9: 1600, 10: 1000})

    def test_live_command_cannot_cross_saved_limit(self):
        with self.assertRaises(ValueError):
            self.sim.validate_command({7: 1906, 8: 1430, 9: 1600, 10: 1400},
                                      self.sim.expected_settings(), 400)

    def test_live_command_cannot_cross_selected_bench_cap(self):
        with self.assertRaises(ValueError):
            self.sim.validate_command({7: 1806, 8: 1430, 9: 1600, 10: 1400},
                                      self.sim.expected_settings(), 300)

    def test_bench_cap_cannot_exceed_requested_400(self):
        with self.assertRaises(ValueError):
            self.sim.validate_bench_cap(401)


if __name__ == "__main__":
    unittest.main()
