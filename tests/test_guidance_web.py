import json
import sys
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autonomous_guidance import FrameHub, FrameSnapshot
from guidance_web import make_monitor_server
from servo_controller import NEUTRAL


class FakeRuntime:
    def __init__(self):
        self.camera_calls = 0
        self.servo_calls = 0
        self.stop_and_neutral_calls = 0
        self.frame_hub = FrameHub()
        self.frame_hub.publish(FrameSnapshot(
            sequence=0, captured_at=1.0, raw_frame=None, detection=None,
            jpeg=b"fake-jpeg", state="locked", target=(100, 120),
            requested_us=400, pulses=dict(NEUTRAL), fps=9.5, reason="",
            acquire_count=3, observe_only=False, recording="active",
            recording_clip="clip.mp4", recording_frames=120,
            recording_dropped=2, recording_error=""))

    def snapshot(self):
        return self.frame_hub.latest().status()

    def stop_and_neutral(self):
        self.stop_and_neutral_calls += 1
        latest = self.frame_hub.latest()
        self.frame_hub.publish(FrameSnapshot(
            sequence=0, captured_at=2.0, raw_frame=latest.raw_frame,
            detection=latest.detection, jpeg=latest.jpeg, state="inhibited",
            target=None, requested_us=0, pulses=dict(NEUTRAL), fps=latest.fps,
            reason="operator stop", acquire_count=0, observe_only=False))
        return self.snapshot()


class RunningServer:
    def __init__(self, runtime):
        self.server = make_monitor_server(runtime, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"
        return self

    def __exit__(self, *unused):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class GuidanceWebTests(unittest.TestCase):
    def test_two_stream_clients_do_not_capture_or_command_hardware(self):
        runtime = FakeRuntime()
        with RunningServer(runtime) as running:
            for _ in range(2):
                with urlopen(running.base + "/stream.mjpg", timeout=2) as response:
                    self.assertEqual(response.readline(), b"--frame\r\n")
                    self.assertIn(b"image/jpeg", response.readline())
                    length = int(response.readline().split(b":", 1)[1])
                    self.assertEqual(response.readline(), b"\r\n")
                    self.assertEqual(response.read(length), b"fake-jpeg")
        self.assertEqual(runtime.camera_calls, 0)
        self.assertEqual(runtime.servo_calls, 0)

    def test_state_returns_latest_autonomous_status(self):
        runtime = FakeRuntime()
        with RunningServer(runtime) as running:
            with urlopen(running.base + "/state", timeout=2) as response:
                state = json.load(response)
        self.assertEqual(state["state"], "locked")
        self.assertEqual(state["requested_us"], 400)
        self.assertEqual(state["fps"], 9.5)
        self.assertEqual(state["recording"], "active")
        self.assertEqual(state["recording_clip"], "clip.mp4")
        self.assertEqual(state["recording_frames"], 120)
        self.assertEqual(state["recording_dropped"], 2)
        self.assertEqual(state["recording_error"], "")

    def test_stop_latches_inhibit_and_neutral(self):
        runtime = FakeRuntime()
        with RunningServer(runtime) as running:
            request = Request(running.base + "/stop", data=b"", method="POST")
            with urlopen(request, timeout=2) as response:
                result = json.load(response)
        self.assertEqual(runtime.stop_and_neutral_calls, 1)
        self.assertEqual(runtime.snapshot()["state"], "inhibited")
        self.assertIn("restart", result["message"].lower())

    def test_page_has_status_and_stop_but_no_start_control(self):
        runtime = FakeRuntime()
        with RunningServer(runtime) as running:
            with urlopen(running.base + "/", timeout=2) as response:
                page = response.read().decode("utf-8")
        self.assertIn("Stop and neutral", page)
        self.assertIn("/state", page)
        self.assertIn("recording", page.lower())
        self.assertNotIn("Start fin test", page)


if __name__ == "__main__":
    unittest.main()
