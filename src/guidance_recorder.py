"""Nonblocking rolling recording for annotated guidance frames."""

from __future__ import annotations

import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Thread


@dataclass(frozen=True)
class RecorderStatus:
    state: str
    current_clip: str | None = None
    frames_written: int = 0
    dropped_frames: int = 0
    error: str = ""


def build_ffmpeg_command(directory, fps, bitrate, segment_seconds,
                         session_token):
    pattern = str(
        Path(directory) /
        f"guidance-%Y%m%dT%H%M%SZ-{session_token}.mp4")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "image2pipe", "-framerate", str(fps),
        "-vcodec", "mjpeg", "-i", "pipe:0", "-an",
        "-c:v", "h264_v4l2m2m", "-b:v", str(bitrate),
        "-pix_fmt", "yuv420p", "-g", "30",
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1", "-strftime", "1", pattern,
    ]


def _recording_files(directory):
    return sorted(
        Path(directory).glob("guidance-*.mp4"),
        key=lambda path: (path.stat().st_mtime_ns, path.name))


def prune_recordings(directory, keep_completed, active_path=None):
    if keep_completed < 0:
        raise ValueError("keep_completed must not be negative")
    active = Path(active_path).resolve() if active_path is not None else None
    completed = [
        path for path in _recording_files(directory)
        if active is None or path.resolve() != active
    ]
    for path in completed[:-keep_completed or None]:
        path.unlink()


class RollingVideoRecorder:
    def __init__(self, directory, *, fps=15, bitrate=2_000_000,
                 segment_seconds=60, keep_segments=60,
                 process_factory=subprocess.Popen,
                 clock=time.monotonic, session_token=None):
        if fps <= 0 or bitrate <= 0 or segment_seconds <= 0:
            raise ValueError("Recorder timing and bitrate must be positive")
        if keep_segments < 1:
            raise ValueError("Recorder must keep at least one segment")
        self.directory = Path(directory)
        self.fps = float(fps)
        self.bitrate = int(bitrate)
        self.segment_seconds = int(segment_seconds)
        self.keep_segments = int(keep_segments)
        self.process_factory = process_factory
        self.clock = clock
        self.session_token = session_token or secrets.token_hex(2)
        self._condition = Condition()
        self._state = "stopped"
        self._current_clip = None
        self._frames_written = 0
        self._dropped_frames = 0
        self._error = ""
        self._pending_frame = None
        self._last_frame = None
        self._stop_requested = False
        self._process = None
        self._thread = None

    def status(self):
        with self._condition:
            return RecorderStatus(
                state=self._state,
                current_clip=self._current_clip,
                frames_written=self._frames_written,
                dropped_frames=self._dropped_frames,
                error=self._error)

    def start(self):
        with self._condition:
            if self._state == "active":
                return True
            self._state = "starting"
            self._error = ""
            self._stop_requested = False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            command = build_ffmpeg_command(
                self.directory, self.fps, self.bitrate,
                self.segment_seconds, self.session_token)
            environment = os.environ.copy()
            environment["TZ"] = "UTC"
            process = self.process_factory(
                command, stdin=subprocess.PIPE, stderr=None, env=environment)
            if process.stdin is None:
                raise RuntimeError("FFmpeg stdin pipe was not created")
        except Exception as error:
            with self._condition:
                self._state = "failed"
                self._error = f"Could not start FFmpeg: {error}"
            return False
        with self._condition:
            self._process = process
            self._state = "active"
            self._thread = Thread(
                target=self._run, name="guidance-recorder", daemon=True)
            thread = self._thread
        thread.start()
        return True

    def publish(self, jpeg, captured_at):
        del captured_at
        if not isinstance(jpeg, (bytes, bytearray, memoryview)):
            raise TypeError("Recorded frame must be JPEG bytes")
        payload = bytes(jpeg)
        with self._condition:
            if self._state != "active" or self._stop_requested:
                return False
            if self._pending_frame is not None:
                self._dropped_frames += 1
            self._pending_frame = payload
            self._condition.notify_all()
            return True

    def _latest_clip(self):
        clips = _recording_files(self.directory)
        return clips[-1] if clips else None

    def _set_failed(self, error):
        with self._condition:
            if self._stop_requested:
                return
            self._state = "failed"
            self._error = str(error) or error.__class__.__name__
            self._condition.notify_all()

    def _run(self):
        interval = 1.0 / self.fps
        next_due = self.clock()
        try:
            while True:
                with self._condition:
                    while (not self._stop_requested and
                           self._pending_frame is None and
                           self._last_frame is None):
                        self._condition.wait(timeout=interval)
                    if self._stop_requested:
                        return
                    remaining = next_due - self.clock()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue
                    if self._pending_frame is not None:
                        self._last_frame = self._pending_frame
                        self._pending_frame = None
                    frame = self._last_frame
                    process = self._process
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"FFmpeg exited with status {return_code}")
                process.stdin.write(frame)
                process.stdin.flush()
                with self._condition:
                    self._frames_written += 1
                    written = self._frames_written
                if written % max(1, round(self.fps)) == 0:
                    active = self._latest_clip()
                    prune_recordings(
                        self.directory, self.keep_segments, active)
                    with self._condition:
                        self._current_clip = str(active) if active else None
                now = self.clock()
                next_due = max(next_due + interval, now)
        except Exception as error:
            self._set_failed(error)

    def close(self, timeout=5.0):
        deadline = self.clock() + max(0.0, timeout)
        with self._condition:
            self._stop_requested = True
            self._condition.notify_all()
            thread = self._thread
            process = self._process
        if thread is not None:
            thread.join(timeout=max(0.0, deadline - self.clock()))
        if process is not None:
            if thread is not None and thread.is_alive():
                try:
                    process.terminate()
                except Exception:
                    pass
                thread.join(timeout=0.2)
            try:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.wait(timeout=max(0.0, deadline - self.clock()))
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=0.2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
        try:
            prune_recordings(self.directory, self.keep_segments,
                             active_path=None)
        except Exception as error:
            self._set_failed(error)
        with self._condition:
            if self._state != "failed":
                self._state = "stopped"
