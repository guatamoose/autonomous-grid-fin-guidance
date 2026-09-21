import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_ball_sim import NEUTRAL, expected_settings
from guidance_state import GuidanceController, Observation, State


def obs(center, captured_at, area=0.10, frame_size=(640, 480)):
    return Observation(center=center, frame_size=frame_size,
                       area_fraction=area, captured_at=captured_at)


def obs_at_radius(radius_fraction, captured_at, area=0.10):
    radius = min(640, 480) / 2
    return obs((round(320 + radius_fraction * radius), 240),
               captured_at, area)


def locked_controller(radius_fraction=0.40):
    controller = GuidanceController(expected_settings(), max_offset=400)
    for index in range(3):
        controller.update(obs_at_radius(radius_fraction, index * 0.1), index * 0.1)
    return controller


class GuidanceStateTests(unittest.TestCase):
    def test_three_compatible_frames_establish_lock(self):
        controller = GuidanceController(expected_settings(), max_offset=400)
        self.assertEqual(controller.update(obs((200, 240), 0.0), 0.0).state,
                         State.ACQUIRING)
        self.assertEqual(controller.update(obs((202, 239), 0.1), 0.1).state,
                         State.ACQUIRING)
        output = controller.update(obs((201, 241), 0.2), 0.2)
        self.assertEqual(output.state, State.LOCKED)
        self.assertNotEqual(output.pulses, NEUTRAL)

    def test_one_frame_flash_returns_to_search_without_movement(self):
        controller = GuidanceController(expected_settings(), max_offset=400)
        first = controller.update(obs((200, 240), 0.0), 0.0)
        output = controller.update(None, 0.1)
        self.assertEqual(first.pulses, NEUTRAL)
        self.assertEqual(output.state, State.SEARCHING)
        self.assertEqual(output.pulses, NEUTRAL)

    def test_incompatible_detection_restarts_acquisition(self):
        controller = GuidanceController(expected_settings(), max_offset=400)
        controller.update(obs((200, 240), 0.0), 0.0)
        controller.update(obs((202, 241), 0.1), 0.1)
        output = controller.update(obs((600, 40), 0.2), 0.2)
        self.assertEqual(output.state, State.ACQUIRING)
        self.assertEqual(output.acquire_count, 1)
        self.assertEqual(output.pulses, NEUTRAL)

    def test_locked_target_loss_becomes_neutral_after_half_second(self):
        controller = locked_controller()
        previous = controller.last_output
        lost = controller.update(None, 1.0)
        held = controller.update(None, 1.49)
        neutral = controller.update(None, 1.51)
        self.assertEqual(lost.state, State.LOST)
        self.assertEqual(held.pulses, previous.pulses)
        self.assertEqual(neutral.state, State.SEARCHING)
        self.assertEqual(neutral.pulses, NEUTRAL)

    def test_inhibit_latches_neutral(self):
        controller = locked_controller()
        self.assertEqual(controller.inhibit().state, State.INHIBITED)
        output = controller.update(obs_at_radius(0.9, 1.0), 1.0)
        self.assertEqual(output.state, State.INHIBITED)
        self.assertEqual(output.pulses, NEUTRAL)

    def test_fault_latches_neutral_and_reason(self):
        controller = locked_controller()
        output = controller.fault("camera stopped")
        self.assertEqual(output.state, State.FAULT)
        self.assertEqual(output.pulses, NEUTRAL)
        self.assertEqual(output.reason, "camera stopped")

    def test_locked_zone_holds_near_25_percent_boundary(self):
        controller = locked_controller(0.24)
        self.assertEqual(controller.update(obs_at_radius(0.255, 1.0), 1.0).requested_us,
                         100)
        self.assertEqual(controller.update(obs_at_radius(0.29, 1.1), 1.1).requested_us,
                         200)

    def test_hysteresis_allows_correction_to_decrease_after_margin(self):
        controller = locked_controller(0.55)
        self.assertEqual(controller.update(obs_at_radius(0.49, 1.0), 1.0).requested_us,
                         300)
        self.assertEqual(controller.update(obs_at_radius(0.46, 1.1), 1.1).requested_us,
                         200)

    def test_dead_zone_immediately_requests_neutral(self):
        controller = locked_controller(0.20)
        output = controller.update(obs_at_radius(0.04, 1.0), 1.0)
        self.assertEqual(output.requested_us, 0)
        self.assertEqual(output.pulses, NEUTRAL)


if __name__ == "__main__":
    unittest.main()
