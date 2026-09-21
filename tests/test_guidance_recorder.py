import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guidance_recorder import (RollingVideoRecorder, build_ffmpeg_command,
                               prune_recordings)


class FakeStdin:
    def __init__(self, gate=None):
        self.gate = gate
        self.write_started = threading.Event()
        self.frames = []
        self.closed = False

    def write(self, payload):
        self.write_started.set()
        if self.gate is not None:
            self.gate.wait(timeout=2)
        if self.closed:
            raise BrokenPipeError("closed")
        self.frames.append(payload)
        return len(payload)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *, poll_code=None, gate=None, wait_timeout=False):
        self.stdin = FakeStdin(gate)
        self.poll_code = poll_code
        self.wait_timeout = wait_timeout
        self.terminate_called = False
        self.kill_called = False

    def poll(self):
        return self.poll_code

    def wait(self, timeout=None):
        if self.wait_timeout and not self.terminate_called:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0 if self.poll_code is None else self.poll_code

    def terminate(self):
        self.terminate_called = True
        self.poll_code = -15

    def kill(self):
        self.kill_called = True
        self.poll_code = -9


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def make_recorder(self, process):
        return RollingVideoRecorder(
            self.directory, fps=100, bitrate=2_000_000,
            segment_seconds=60, keep_segments=60,
            process_factory=lambda *args, **kwargs: process,
            session_token="a1b2")

    def test_publish_replaces_pending_frame_without_blocking(self):
        gate = threading.Event()
        process = FakeProcess(gate=gate)
        recorder = self.make_recorder(process)
        recorder.start()
        self.assertTrue(recorder.publish(b"frame-1", 1.0))
        self.assertTrue(process.stdin.write_started.wait(timeout=1))

        self.assertTrue(recorder.publish(b"frame-2", 1.1))
        started = time.monotonic()
        self.assertTrue(recorder.publish(b"frame-3", 1.2))
        self.assertLess(time.monotonic() - started, 0.05)
        self.assertEqual(recorder.status().dropped_frames, 1)

        gate.set()
        recorder.close()

    def test_encoder_failure_is_reported_without_raise_from_publish(self):
        process = FakeProcess(poll_code=1)
        recorder = self.make_recorder(process)
        recorder.start()
        self.assertTrue(recorder.publish(b"jpeg", 1.0))
        wait_for(lambda: recorder.status().state == "failed")
        self.assertIn("FFmpeg exited", recorder.status().error)
        self.assertFalse(recorder.publish(b"next", 1.1))
        recorder.close()

    def test_close_has_bounded_wait_then_terminates_process(self):
        process = FakeProcess(wait_timeout=True)
        recorder = self.make_recorder(process)
        recorder.start()
        recorder.close(timeout=0.01)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.terminate_called)

    def test_ffmpeg_command_uses_required_hardware_recording_settings(self):
        command = build_ffmpeg_command(
            Path("/recordings"), fps=15, bitrate=2_000_000,
            segment_seconds=60, session_token="a1b2")
        self.assertIn("h264_v4l2m2m", command)
        self.assertIn("2000000", command)
        self.assertIn("60", command)
        self.assertIn("30", command)
        self.assertTrue(command[-1].endswith(
            "guidance-%Y%m%dT%H%M%SZ-a1b2.mp4"))

    def create_clips(self, count):
        clips = []
        for index in range(count):
            path = self.directory / f"guidance-20260921T{index:06d}Z-a1b2.mp4"
            path.write_bytes(b"clip")
            os.utime(path, (index + 1, index + 1))
            clips.append(path)
        return clips

    def test_retention_keeps_sixty_completed_plus_active_and_ignores_other_files(self):
        clips = self.create_clips(65)
        unrelated = self.directory / "notes.txt"
        unrelated.write_text("keep me", encoding="utf-8")
        active = clips[-1]
        prune_recordings(self.directory, keep_completed=60,
                         active_path=active)
        remaining = sorted(
            self.directory.glob("guidance-*.mp4"),
            key=lambda path: (path.stat().st_mtime_ns, path.name))
        self.assertEqual(remaining, clips[-61:])
        self.assertTrue(unrelated.exists())

    def test_closed_recorder_prunes_to_exactly_sixty(self):
        clips = self.create_clips(65)
        prune_recordings(self.directory, keep_completed=60,
                         active_path=None)
        remaining = sorted(
            self.directory.glob("guidance-*.mp4"),
            key=lambda path: (path.stat().st_mtime_ns, path.name))
        self.assertEqual(remaining, clips[-60:])

    def test_session_token_prevents_same_second_filename_collision(self):
        first = build_ffmpeg_command(
            self.directory, 15, 2_000_000, 60, "a1b2")[-1]
        second = build_ffmpeg_command(
            self.directory, 15, 2_000_000, 60, "c3d4")[-1]
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
