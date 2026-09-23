import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_guidance import (CameraSample, GuidanceRuntime,
                                 apply_camera_exposure)
from guidance_recorder import RecorderStatus
from orange_pad import Detection
from servo_controller import NEUTRAL, expected_settings


FRAME = np.zeros((480, 640, 3), dtype=np.uint8)
PAD = Detection(center=(620, 240), bbox=(560, 180, 639, 300),
                area_fraction=0.08, fill_fraction=0.8)


class MutableClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeCamera:
    def __init__(self, clock, samples):
        self.clock = clock
        self.samples = list(samples)
        self.stopped = False
        self.closed = False

    def capture(self):
        frame, source_timestamp, now = self.samples.pop(0)
        self.clock.now = now
        return CameraSample(frame, source_timestamp)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeServo:
    def __init__(self):
        self.settings = expected_settings()
        self.cycles = []
        self.health_checks = []
        self.closed = False

    def check_health(self, now=None):
        self.health_checks.append(now)

    def send_cycle(self, pulses, now=None):
        self.cycles.append(dict(pulses))

    def neutral(self):
        self.send_cycle(NEUTRAL)

    def close(self):
        self.closed = True


class SequenceDetector:
    def __init__(self, detections):
        self.detections = list(detections)

    def __call__(self, frame, **kwargs):
        return self.detections.pop(0)


class FakeRecorder:
    def __init__(self, state="active", error="", events=None):
        self.frames = []
        self.state = state
        self.error = error
        self.closed = False
        self.events = events

    def publish(self, jpeg, captured_at):
        self.frames.append((jpeg, captured_at))
        return self.state == "active"

    def status(self):
        return RecorderStatus(
            state=self.state, current_clip="clip.mp4",
            frames_written=len(self.frames), dropped_frames=0,
            error=self.error)

    def close(self, timeout=5.0):
        self.closed = True
        if self.events is not None:
            self.events.append("recorder-close")


def samples(*times, source_times=None):
    source_times = times if source_times is None else source_times
    return [(FRAME, source, now) for source, now in zip(source_times, times)]


def make_runtime(camera_samples, detections, *, observe_only=False, **kwargs):
    clock = MutableClock()
    camera = FakeCamera(clock, camera_samples)
    servo = FakeServo()
    renderer = kwargs.pop(
        "renderer", lambda frame, detection, telemetry: b"jpeg")
    runtime = GuidanceRuntime(
        camera, servo, detector=SequenceDetector(detections), clock=clock,
        renderer=renderer, observe_only=observe_only, max_offset=400,
        logger=None, **kwargs)
    return runtime


class GuidanceRuntimeTests(unittest.TestCase):
    def test_runtime_publishes_annotated_jpeg_to_recorder(self):
        recorder = FakeRecorder()
        runtime = make_runtime(samples(0.0), [None], recorder=recorder)
        runtime.run_steps(1)
        self.assertEqual(recorder.frames, [(b"jpeg", 0.0)])
        self.assertEqual(runtime.snapshot()["recording"], "active")

    def test_recorder_failure_does_not_fault_guidance(self):
        recorder = FakeRecorder(state="failed", error="disk full")
        runtime = make_runtime(samples(0.0, 0.1, 0.2), [PAD] * 3,
                               recorder=recorder)
        self.assertEqual(runtime.run_steps(3), 0)
        self.assertEqual(runtime.snapshot()["state"], "locked")
        self.assertEqual(runtime.snapshot()["recording"], "failed")
        self.assertEqual(runtime.snapshot()["recording_error"], "disk full")

    def test_shutdown_neutralizes_before_closing_recorder(self):
        events = []
        recorder = FakeRecorder(events=events)
        runtime = make_runtime(samples(0.0), [None], recorder=recorder)
        runtime.servo.send_cycle = (
            lambda pulses, now=None: events.append("servo-neutral"))
        stop = threading.Event()
        stop.set()
        runtime.run(stop)
        self.assertLess(events.index("servo-neutral"),
                        events.index("recorder-close"))

    def test_target_fps_sets_loop_interval(self):
        runtime = make_runtime(samples(0.0), [None], target_fps=15)
        self.assertAlmostEqual(runtime.loop_interval, 1 / 15)

    def test_renderer_receives_actual_neutral_in_observe_only(self):
        captured = []

        def renderer(frame, detection, telemetry):
            captured.append(telemetry)
            return b"jpeg"

        runtime = make_runtime(samples(0.0, 0.1, 0.2), [PAD] * 3,
                               observe_only=True, renderer=renderer)
        runtime.run_steps(3)
        self.assertEqual(captured[-1].requested_us, 400)
        self.assertEqual(captured[-1].pulses, NEUTRAL)
        self.assertTrue(captured[-1].observe_only)

    def test_browser_is_not_required_for_camera_and_servo_updates(self):
        runtime = make_runtime(samples(0.0, 0.1, 0.2, 0.3), [PAD] * 4)
        runtime.run_steps(4)
        self.assertEqual(runtime.frame_hub.sequence, 4)
        self.assertEqual(runtime.snapshot()["state"], "locked")
        self.assertNotEqual(runtime.servo.cycles[-1], NEUTRAL)

    def test_search_and_first_two_acquisition_frames_are_neutral(self):
        runtime = make_runtime(samples(0.0, 0.1, 0.2), [None, PAD, PAD])
        runtime.run_steps(3)
        self.assertEqual(runtime.servo.cycles, [NEUTRAL, NEUTRAL, NEUTRAL])

    def test_outer_zone_requests_full_400_microseconds(self):
        runtime = make_runtime(samples(0.0, 0.1, 0.2), [PAD] * 3)
        runtime.run_steps(3)
        status = runtime.snapshot()
        self.assertEqual(status["requested_us"], 400)
        self.assertTrue(all(
            expected_settings()[channel]["min"] <= pulse <=
            expected_settings()[channel]["max"]
            for channel, pulse in status["pulses"].items()))

    def test_observe_only_tracks_lock_but_keeps_real_outputs_neutral(self):
        runtime = make_runtime(samples(0.0, 0.1, 0.2), [PAD] * 3,
                               observe_only=True)
        runtime.run_steps(3)
        self.assertEqual(runtime.snapshot()["state"], "locked")
        self.assertEqual(runtime.snapshot()["requested_us"], 400)
        self.assertEqual(runtime.servo.cycles[-1], NEUTRAL)
        self.assertEqual(runtime.snapshot()["pulses"], NEUTRAL)

    def test_frozen_camera_timestamp_faults_and_neutralizes(self):
        runtime = make_runtime(
            samples(1.0, 1.2, 1.4, 1.6,
                    source_times=(1.0, 1.0, 1.0, 1.0)), [PAD] * 4)
        runtime.run_steps(4)
        self.assertEqual(runtime.snapshot()["state"], "fault")
        self.assertIn("stale", runtime.snapshot()["reason"])
        self.assertEqual(runtime.servo.cycles[-1], NEUTRAL)

    def test_run_always_neutralizes_and_closes_hardware(self):
        runtime = make_runtime(samples(0.0), [RuntimeError("camera pipeline")])

        def raising_detector(frame, **kwargs):
            raise RuntimeError("camera pipeline")

        runtime.detector = raising_detector
        exit_code = runtime.run(stop_event=None)
        self.assertEqual(exit_code, 1)
        self.assertEqual(runtime.snapshot()["state"], "fault")
        self.assertEqual(runtime.servo.cycles[-1], NEUTRAL)
        self.assertTrue(runtime.servo.closed)
        self.assertTrue(runtime.camera.stopped)
        self.assertTrue(runtime.camera.closed)


class CameraExposureTests(unittest.TestCase):
    def test_zero_ev_restores_normal_auto_exposure_constraint(self):
        class FakeCameraControls:
            def __init__(self):
                self.values = None

            def set_controls(self, values):
                self.values = values

        fake_controls = types.SimpleNamespace(
            AeConstraintModeEnum=types.SimpleNamespace(
                Highlight="highlight", Normal="normal"))
        fake_libcamera = types.SimpleNamespace(controls=fake_controls)
        camera = FakeCameraControls()

        with patch.dict(sys.modules, {"libcamera": fake_libcamera}):
            apply_camera_exposure(camera, 0.0)

        self.assertEqual(camera.values, {
            "AeEnable": True,
            "AeConstraintMode": "normal",
            "ExposureValue": 0.0,
        })

    def test_applies_negative_ev_with_highlight_constraint(self):
        class FakeCameraControls:
            def __init__(self):
                self.values = None

            def set_controls(self, values):
                self.values = values

        fake_controls = types.SimpleNamespace(
            AeConstraintModeEnum=types.SimpleNamespace(Highlight="highlight"))
        fake_libcamera = types.SimpleNamespace(controls=fake_controls)
        camera = FakeCameraControls()

        with patch.dict(sys.modules, {"libcamera": fake_libcamera}):
            apply_camera_exposure(camera, -1.0)

        self.assertEqual(camera.values, {
            "AeEnable": True,
            "AeConstraintMode": "highlight",
            "ExposureValue": -1.0,
        })


if __name__ == "__main__":
    unittest.main()
