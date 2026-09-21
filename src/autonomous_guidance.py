"""Always-on camera guidance runtime independent of the browser monitor."""

from __future__ import annotations

import argparse
import io
import logging
import signal
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Event, Lock, Thread

from camera_zone_preview import OverlayTelemetry, overlay_zones
from guidance_recorder import RecorderStatus, RollingVideoRecorder
from guidance_state import GuidanceController, Observation, State
from orange_pad import detect_orange_pad
from servo_controller import NEUTRAL


@dataclass(frozen=True)
class CameraSample:
    frame: object
    source_timestamp: float | int


@dataclass(frozen=True)
class FrameSnapshot:
    sequence: int
    captured_at: float
    raw_frame: object
    detection: object | None
    jpeg: bytes
    state: str
    target: tuple[int, int] | None
    requested_us: int
    pulses: dict[int, int]
    fps: float
    reason: str
    acquire_count: int
    observe_only: bool
    recording: str = "off"
    recording_clip: str | None = None
    recording_frames: int = 0
    recording_dropped: int = 0
    recording_error: str = ""

    def status(self):
        return {
            "sequence": self.sequence,
            "captured_at": self.captured_at,
            "state": self.state,
            "target": self.target,
            "requested_us": self.requested_us,
            "pulses": dict(self.pulses),
            "fps": self.fps,
            "reason": self.reason,
            "acquire_count": self.acquire_count,
            "observe_only": self.observe_only,
            "recording": self.recording,
            "recording_clip": self.recording_clip,
            "recording_frames": self.recording_frames,
            "recording_dropped": self.recording_dropped,
            "recording_error": self.recording_error,
        }


class FrameHub:
    """Thread-safe publication point for the monitor server."""

    def __init__(self):
        self._lock = Lock()
        self._latest = None
        self.sequence = 0

    def publish(self, snapshot):
        with self._lock:
            self.sequence += 1
            snapshot = replace(snapshot, sequence=self.sequence)
            self._latest = snapshot
            return snapshot

    def latest(self):
        with self._lock:
            return self._latest


class PicameraSource:
    """Picamera2 adapter that exposes the sensor timestamp with each frame."""

    def __init__(self, camera):
        self.camera = camera

    def capture(self):
        request = self.camera.capture_request()
        try:
            frame = request.make_array("main")
            metadata = request.get_metadata()
            timestamp = metadata.get("SensorTimestamp", time.monotonic_ns())
            return CameraSample(frame, timestamp)
        finally:
            request.release()

    def stop(self):
        self.camera.stop()

    def close(self):
        self.camera.close()


def apply_camera_exposure(camera, exposure_value=-1.0):
    from libcamera import controls

    camera.set_controls({
        "AeEnable": True,
        "AeConstraintMode": controls.AeConstraintModeEnum.Highlight,
        "ExposureValue": float(exposure_value),
    })


def open_camera_source(size=(640, 480), exposure_value=-1.0):
    from picamera2 import Picamera2

    camera = Picamera2()
    camera.configure(camera.create_preview_configuration(
        main={"size": size, "format": "RGB888"}))
    apply_camera_exposure(camera, exposure_value)
    camera.start()
    time.sleep(1)
    return PicameraSource(camera)


def configure_logging(log_path=None):
    logger = logging.getLogger("rocket-guidance")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    stderr = logging.StreamHandler()
    stderr.setFormatter(formatter)
    logger.addHandler(stderr)
    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            path, maxBytes=2_000_000, backupCount=4)
        rotating.setFormatter(formatter)
        logger.addHandler(rotating)
    return logger


def render_jpeg(frame, detection, telemetry, channel_order="BGR"):
    image = overlay_zones(frame, channel_order=channel_order,
                          detection=detection, telemetry=telemetry)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=78)
    return output.getvalue()


class GuidanceRuntime:
    def __init__(self, camera, servo, *, detector=detect_orange_pad,
                 renderer=None, clock=time.monotonic, sleeper=time.sleep,
                 frame_hub=None, max_offset=400, observe_only=False,
                 channel_order="BGR", stale_after=0.5,
                 target_fps=15.0, wall_clock=time.time, recorder=None,
                 logger=None):
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")
        self.camera = camera
        self.servo = servo
        self.detector = detector
        self.clock = clock
        self.wall_clock = wall_clock
        self.recorder = recorder
        self.sleeper = sleeper
        self.frame_hub = frame_hub or FrameHub()
        self.max_offset = max_offset
        self.observe_only = observe_only
        self.channel_order = channel_order
        self.stale_after = stale_after
        self.loop_interval = 1.0 / target_fps
        self.logger = logger or logging.getLogger("rocket-guidance")
        self.renderer = renderer or (
            lambda frame, detection, telemetry: render_jpeg(
                frame, detection, telemetry,
                channel_order=self.channel_order))
        if servo.settings is None:
            raise ValueError("Servo controller must be connected before guidance starts")
        self.guidance = GuidanceController(
            servo.settings, max_offset=max_offset)
        self._output_lock = Lock()
        self._last_source_timestamp = None
        self._last_fresh_at = None
        self._started_at = None
        self._frames = 0
        self._last_state = None
        self._last_sample_log_at = float("-inf")
        self._last_frame = None
        self._last_detection = None
        self._recorder_error = ""

    def snapshot(self):
        latest = self.frame_hub.latest()
        if latest is None:
            return {
                "sequence": 0, "state": self.guidance.state.value,
                "target": None, "requested_us": 0,
                "pulses": dict(NEUTRAL), "fps": 0.0, "reason": "",
                "acquire_count": 0, "observe_only": self.observe_only,
                "recording": "off" if self.recorder is None else "starting",
                "recording_clip": None, "recording_frames": 0,
                "recording_dropped": 0, "recording_error": "",
            }
        return latest.status()

    def _recorder_status(self):
        if self.recorder is None:
            return RecorderStatus(state="off")
        if self._recorder_error:
            return RecorderStatus(state="failed", error=self._recorder_error)
        try:
            return self.recorder.status()
        except Exception as error:
            self._recorder_error = str(error) or error.__class__.__name__
            self.logger.exception("could not read recorder status")
            return RecorderStatus(state="failed", error=self._recorder_error)

    def _publish(self, now, output, actual_pulses, frame=None,
                 detection=None, jpeg=None, fps=None, recorder_status=None):
        previous = self.frame_hub.latest()
        if frame is None and previous is not None:
            frame = previous.raw_frame
        if detection is None and output.target is not None:
            detection = self._last_detection
        if jpeg is None:
            jpeg = previous.jpeg if previous is not None else b""
        if fps is None:
            fps = previous.fps if previous is not None else 0.0
        recorder_status = recorder_status or self._recorder_status()
        return self.frame_hub.publish(FrameSnapshot(
            sequence=0, captured_at=now, raw_frame=frame,
            detection=detection, jpeg=jpeg, state=output.state.value,
            target=output.target, requested_us=output.requested_us,
            pulses=dict(actual_pulses), fps=fps, reason=output.reason,
            acquire_count=output.acquire_count,
            observe_only=self.observe_only,
            recording=recorder_status.state,
            recording_clip=recorder_status.current_clip,
            recording_frames=recorder_status.frames_written,
            recording_dropped=recorder_status.dropped_frames,
            recording_error=recorder_status.error))

    def _check_freshness(self, source_timestamp, now):
        if source_timestamp != self._last_source_timestamp:
            self._last_source_timestamp = source_timestamp
            self._last_fresh_at = now
            return
        if (self._last_fresh_at is not None and
                now - self._last_fresh_at > self.stale_after):
            raise RuntimeError("camera frame timestamp is stale")

    def _record_logs(self, output, now):
        if output.state != self._last_state:
            self.logger.info("state=%s reason=%s", output.state.value,
                             output.reason or "-")
            self._last_state = output.state
        if now - self._last_sample_log_at >= 1.0:
            recorder = self._recorder_status()
            self.logger.info(
                "target=%s requested_us=%s pulses=%s recording=%s dropped=%s",
                output.target, output.requested_us, output.pulses,
                recorder.state, recorder.dropped_frames)
            self._last_sample_log_at = now

    @staticmethod
    def _direction(output, frame_size):
        width, height = frame_size
        if output.target is not None:
            x, y = output.target
            dx, dy = x - width / 2, height / 2 - y
        else:
            dx = output.pulses[9] - NEUTRAL[9]
            dy = output.pulses[7] - NEUTRAL[7]
        horizontal = "right" if dx > 0 else "left" if dx < 0 else ""
        vertical = "up" if dy > 0 else "down" if dy < 0 else ""
        return "-".join(part for part in (horizontal, vertical) if part) or "center"

    def _step(self):
        sample = self.camera.capture()
        now = self.clock()
        if self._started_at is None:
            self._started_at = now
        self._check_freshness(sample.source_timestamp, now)
        detection = self.detector(
            sample.frame, channel_order=self.channel_order, sample_step=8)
        height, width = sample.frame.shape[:2]
        observation = None
        if detection is not None:
            observation = Observation(
                center=detection.center, frame_size=(width, height),
                area_fraction=detection.area_fraction,
                captured_at=now)
        output = self.guidance.update(observation, now)
        actual_pulses = dict(NEUTRAL if self.observe_only else output.pulses)
        with self._output_lock:
            self.servo.check_health(now=now)
            self.servo.send_cycle(actual_pulses, now=now)
        self._frames += 1
        elapsed = max(now - self._started_at, 1e-9)
        fps = self._frames / elapsed if self._frames > 1 else 0.0
        recorder_before = self._recorder_status()
        telemetry = OverlayTelemetry(
            state=output.state.value,
            acquire_count=output.acquire_count,
            requested_us=output.requested_us,
            direction=self._direction(output, (width, height)),
            pulses=dict(actual_pulses),
            neutrals=dict(NEUTRAL),
            observe_only=self.observe_only,
            fps=fps,
            recording=recorder_before.state,
            timestamp=datetime.fromtimestamp(
                self.wall_clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        jpeg = self.renderer(sample.frame, detection, telemetry)
        if self.recorder is not None:
            try:
                self.recorder.publish(jpeg, now)
            except Exception as error:
                self._recorder_error = str(error) or error.__class__.__name__
                self.logger.exception("could not publish recording frame")
        recorder_after = self._recorder_status()
        self._last_frame = sample.frame
        self._last_detection = detection
        self._publish(now, output, actual_pulses, sample.frame,
                      detection, jpeg, fps, recorder_after)
        self._record_logs(output, now)
        return output

    def _fault_and_neutral(self, error):
        reason = str(error) or error.__class__.__name__
        output = self.guidance.fault(reason)
        self.logger.exception("guidance fault: %s", reason)
        try:
            with self._output_lock:
                self.servo.send_cycle(NEUTRAL, now=self.clock())
        except Exception:
            self.logger.exception("could not command neutral after fault")
        self._publish(self.clock(), output, NEUTRAL,
                      self._last_frame, self._last_detection)

    def run_steps(self, count):
        for _ in range(count):
            try:
                self._step()
            except Exception as error:
                self._fault_and_neutral(error)
                return 1
        return 0

    def stop_and_neutral(self):
        output = self.guidance.inhibit()
        with self._output_lock:
            self.servo.send_cycle(NEUTRAL, now=self.clock())
        self._publish(self.clock(), output, NEUTRAL,
                      self._last_frame, self._last_detection)
        self._record_logs(output, self.clock())
        return self.snapshot()

    def run(self, stop_event):
        exit_code = 0
        try:
            while stop_event is None or not stop_event.is_set():
                started = self.clock()
                self._step()
                remaining = self.loop_interval - (self.clock() - started)
                if remaining > 0:
                    self.sleeper(remaining)
        except Exception as error:
            exit_code = 1
            self._fault_and_neutral(error)
        finally:
            try:
                with self._output_lock:
                    self.servo.send_cycle(NEUTRAL, now=self.clock())
            except Exception:
                self.logger.exception("could not command neutral during shutdown")
            if self.recorder is not None:
                try:
                    self.recorder.close(timeout=5.0)
                except Exception:
                    self.logger.exception("could not close recorder")
            try:
                self.servo.close()
            finally:
                try:
                    self.camera.stop()
                finally:
                    self.camera.close()
        return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=57600)
    parser.add_argument("--max-offset", type=int, choices=(200, 300, 400),
                        default=400)
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument("--exposure-value", type=float, default=-1.0)
    parser.add_argument("--recording", type=int, choices=(0, 1), default=1)
    parser.add_argument("--recording-dir",
                        default="/home/pi/rocket/recordings")
    parser.add_argument("--recording-fps", type=float, default=15.0)
    parser.add_argument("--recording-bitrate", type=int, default=2_000_000)
    parser.add_argument("--recording-segment-seconds", type=int, default=60)
    parser.add_argument("--recording-keep-segments", type=int, default=60)
    parser.add_argument("--observe-only", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--log-path", default="/home/pi/rocket/logs/guidance.log")
    args = parser.parse_args(argv)

    from guidance_web import make_monitor_server
    from servo_controller import AsyncServoDispatcher, MavlinkServoController

    logger = configure_logging(args.log_path)
    stop_event = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_unused: stop_event.set())

    servo = None
    camera = None
    runtime = None
    recorder = None
    server = None
    monitor_thread = None
    try:
        servo = MavlinkServoController(
            args.serial, args.baud, max_offset=args.max_offset).connect()
        servo.neutral()
        servo = AsyncServoDispatcher(servo).start()
        camera = open_camera_source(exposure_value=args.exposure_value)
        if args.recording:
            recorder = RollingVideoRecorder(
                args.recording_dir, fps=args.recording_fps,
                bitrate=args.recording_bitrate,
                segment_seconds=args.recording_segment_seconds,
                keep_segments=args.recording_keep_segments)
            recorder.start()
        runtime = GuidanceRuntime(
            camera, servo, max_offset=args.max_offset,
            observe_only=args.observe_only, target_fps=args.target_fps,
            recorder=recorder, logger=logger)
        if not args.no_web:
            server = make_monitor_server(runtime, args.host, args.port)

            def serve_monitor():
                try:
                    server.serve_forever()
                except Exception:
                    logger.exception("monitor server stopped unexpectedly")

            monitor_thread = Thread(target=serve_monitor,
                                    name="guidance-monitor", daemon=True)
            monitor_thread.start()
            logger.info("monitor=http://%s:%s", args.host, args.port)
        logger.info("guidance started observe_only=%s max_offset=%s",
                    args.observe_only, args.max_offset)
        return runtime.run(stop_event)
    except Exception:
        logger.exception("guidance startup failed")
        if runtime is None:
            if servo is not None:
                try:
                    servo.neutral()
                except Exception:
                    logger.exception("could not command startup-fault neutral")
                servo.close()
            if camera is not None:
                try:
                    camera.stop()
                finally:
                    camera.close()
            if recorder is not None:
                recorder.close(timeout=5.0)
        return 1
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if monitor_thread is not None:
            monitor_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
