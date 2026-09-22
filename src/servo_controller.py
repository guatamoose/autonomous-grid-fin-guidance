"""Calibrated, bounded MAVLink control for the four grid-fin servos."""

import time
from threading import Condition, Thread


NEUTRAL = {7: 1505, 8: 1430, 9: 1600, 10: 1400}
TESTED_OFFSET_US = 200
HEARTBEAT_TIMEOUT_SECONDS = 2.5
PARAM_CHECK_INTERVAL_SECONDS = 1.0
PARAM_REQUEST_ATTEMPTS = 3
PARAM_REQUEST_TIMEOUT_SECONDS = 0.35
SERVO_COMMAND_ATTEMPTS = 3
MAX_SERVO_UPDATE_HZ = 12.0


class ServoAcknowledgementTimeout(RuntimeError):
    pass


def validate_bench_cap(max_offset):
    if max_offset not in (200, 300, 400):
        raise ValueError("Bench offset must be 200, 300, or 400 µs")


def expected_settings():
    return {
        7: {"function": 0, "min": 1105, "max": 1905, "trim": 1505},
        8: {"function": 0, "min": 1030, "max": 1830, "trim": 1430},
        9: {"function": 0, "min": 1200, "max": 2000, "trim": 1600},
        10: {"function": 0, "min": 1000, "max": 1800, "trim": 1400},
    }


def validate_settings(settings):
    for channel, expected in expected_settings().items():
        actual = settings.get(channel)
        if actual is None:
            raise ValueError(f"S{channel} settings were not received")
        for field, expected_value in expected.items():
            if int(actual[field]) != expected_value:
                raise ValueError(
                    f"S{channel} {field} is {int(actual[field])}; "
                    f"expected {expected_value}")


def validate_command(pulses, settings, max_offset):
    validate_bench_cap(max_offset)
    if set(pulses) != set(NEUTRAL):
        raise ValueError("All four fin commands are required")
    for channel, pulse in pulses.items():
        if abs(pulse - NEUTRAL[channel]) > max_offset:
            raise ValueError(f"S{channel} command exceeds the selected offset")
        if not settings[channel]["min"] <= pulse <= settings[channel]["max"]:
            raise ValueError(f"S{channel} command exceeds a saved servo limit")


def pulses_for(decision):
    """Map image-space nose direction to the recorded paired-fin signs."""
    x, y = decision.safe_nose_x_us, decision.safe_nose_y_us
    return {
        7: round(NEUTRAL[7] + y),
        8: round(NEUTRAL[8] - x),
        9: round(NEUTRAL[9] + x),
        10: round(NEUTRAL[10] - y),
    }


def bounded_pulses_for(decision, settings):
    """Scale both steering axes together to fit every saved servo limit."""
    requested = pulses_for(decision)
    scale = 1.0
    for channel, pulse in requested.items():
        offset = pulse - NEUTRAL[channel]
        if offset > 0:
            scale = min(scale, (settings[channel]["max"] - NEUTRAL[channel]) / offset)
        elif offset < 0:
            scale = min(scale, (settings[channel]["min"] - NEUTRAL[channel]) / offset)
    scale = max(0.0, min(1.0, scale))
    return {
        channel: round(NEUTRAL[channel] + (pulse - NEUTRAL[channel]) * scale)
        for channel, pulse in requested.items()
    }


class MavlinkServoController:
    def __init__(self, port, baud, max_offset=400, *, connection=None,
                 mavutil_module=None, clock=time.monotonic,
                 require_disarmed=False):
        if mavutil_module is None:
            from pymavlink import mavutil as mavutil_module
        self.mavutil = mavutil_module
        self.port = port
        self.baud = baud
        self.max_offset = max_offset
        self.connection = connection
        self.clock = clock
        self.require_disarmed = require_disarmed
        self.settings = None
        self.armed = False
        self.last_heartbeat_at = None
        self.last_param_check_at = None
        self._param_check_index = 0
        self.connected = False

    def connect(self):
        validate_bench_cap(self.max_offset)
        if self.connection is None:
            self.connection = self.mavutil.mavlink_connection(
                self.port, baud=self.baud, source_system=251)
        heartbeat = self.connection.wait_heartbeat(timeout=8)
        if heartbeat is None:
            raise RuntimeError("No ArduPilot heartbeat")
        self._note_heartbeat(heartbeat)
        self.settings = self._read_settings()
        validate_settings(self.settings)
        self.last_param_check_at = self.clock()
        self.connected = True
        return self

    def _note_heartbeat(self, heartbeat):
        self.armed = bool(
            heartbeat.base_mode &
            self.mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        self.last_heartbeat_at = self.clock()
        if self.require_disarmed and self.armed:
            raise RuntimeError("Flight controller is armed; stopping bench simulation")

    def _read_param(self, name):
        for _attempt in range(PARAM_REQUEST_ATTEMPTS):
            self.connection.mav.param_request_read_send(
                self.connection.target_system, 1, name.encode("ascii"), -1)
            deadline = self.clock() + PARAM_REQUEST_TIMEOUT_SECONDS
            while self.clock() < deadline:
                msg = self.connection.recv_match(blocking=True, timeout=0.05)
                if msg and msg.get_type() == "HEARTBEAT":
                    self._note_heartbeat(msg)
                if msg and msg.get_type() == "PARAM_VALUE":
                    if str(msg.param_id).rstrip("\x00") == name:
                        return msg.param_value
        raise RuntimeError(f"No response for {name}")

    def _read_settings(self):
        return {
            channel: {
                field: self._read_param(f"SERVO{channel}_{field.upper()}")
                for field in ("function", "min", "max", "trim")
            }
            for channel in NEUTRAL
        }

    def _wait_servo_ack(self, channel, timeout=0.5):
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            msg = self.connection.recv_match(blocking=True, timeout=0.05)
            if msg and msg.get_type() == "HEARTBEAT":
                self._note_heartbeat(msg)
                continue
            if not msg or msg.get_type() != "COMMAND_ACK":
                continue
            if msg.command != self.mavutil.mavlink.MAV_CMD_DO_SET_SERVO:
                continue
            if msg.result != self.mavutil.mavlink.MAV_RESULT_ACCEPTED:
                raise RuntimeError(
                    f"S{channel} command rejected: {msg.result}")
            return
        raise ServoAcknowledgementTimeout(
            f"S{channel} command acknowledgement timed out")

    def send_cycle(self, pulses, now=None):
        if not self.connected:
            raise RuntimeError("Servo controller is not connected")
        validate_command(pulses, self.settings, self.max_offset)
        for channel, pwm in pulses.items():
            for confirmation in range(SERVO_COMMAND_ATTEMPTS):
                self.connection.mav.command_long_send(
                    self.connection.target_system, 1,
                    self.mavutil.mavlink.MAV_CMD_DO_SET_SERVO, confirmation,
                    channel, pwm, 0, 0, 0, 0, 0)
                try:
                    self._wait_servo_ack(channel)
                    break
                except ServoAcknowledgementTimeout:
                    if confirmation + 1 == SERVO_COMMAND_ATTEMPTS:
                        raise

    send = send_cycle

    def _drain_heartbeats(self):
        while True:
            msg = self.connection.recv_match(blocking=False)
            if msg is None:
                return
            if msg.get_type() == "HEARTBEAT":
                self._note_heartbeat(msg)

    def check_health(self, now=None):
        if not self.connected:
            raise RuntimeError("Servo controller is not connected")
        now = self.clock() if now is None else now
        self._drain_heartbeats()
        if (self.last_heartbeat_at is None or
                now - self.last_heartbeat_at > HEARTBEAT_TIMEOUT_SECONDS):
            raise RuntimeError("Flight-controller heartbeat is stale")
        if now - self.last_param_check_at >= PARAM_CHECK_INTERVAL_SECONDS:
            checks = [
                (channel, field, expected_value)
                for channel, setting in expected_settings().items()
                for field, expected_value in setting.items()
            ]
            channel, field, expected_value = checks[self._param_check_index]
            actual = self._read_param(f"SERVO{channel}_{field.upper()}")
            if int(actual) != expected_value:
                raise ValueError(
                    f"S{channel} {field} is {int(actual)}; "
                    f"expected {expected_value}")
            self.settings[channel][field] = actual
            self._param_check_index = (self._param_check_index + 1) % len(checks)
            self.last_param_check_at = now

    def neutral(self):
        self.send_cycle(NEUTRAL)

    def close(self):
        if self.connection is None:
            return
        try:
            if self.connected:
                try:
                    self.neutral()
                except Exception:
                    pass
        finally:
            self.connection.close()
            self.connected = False


class ServoLink(MavlinkServoController):
    """Backwards-compatible, disarmed-only controller for bench tools."""
    def __init__(self, port, baud, max_offset):
        super().__init__(port, baud, max_offset, require_disarmed=True)
        self.connect()


class AsyncServoDispatcher:
    """Run acknowledged servo cycles off the camera processing thread."""

    def __init__(self, controller, *, clock=time.monotonic,
                 max_update_hz=MAX_SERVO_UPDATE_HZ):
        if controller.settings is None:
            raise ValueError("Servo controller must be connected")
        if max_update_hz <= 0:
            raise ValueError("max_update_hz must be positive")
        self.controller = controller
        self.settings = controller.settings
        self.clock = clock
        self.min_cycle_interval = 1.0 / max_update_hz
        self._condition = Condition()
        self._pending = None
        self._stop_requested = False
        self._thread = None
        self._error = None
        self._dropped_commands = 0
        self._last_applied = dict(NEUTRAL)

    @property
    def error(self):
        with self._condition:
            return self._error

    @property
    def dropped_commands(self):
        with self._condition:
            return self._dropped_commands

    @property
    def last_applied(self):
        with self._condition:
            return dict(self._last_applied)

    def start(self):
        with self._condition:
            if self._thread is not None:
                return self
            self._thread = Thread(
                target=self._run, name="servo-dispatcher", daemon=True)
            thread = self._thread
        thread.start()
        return self

    def send_cycle(self, pulses, now=None):
        del now
        validate_command(pulses, self.settings, self.controller.max_offset
                         if hasattr(self.controller, "max_offset") else 400)
        with self._condition:
            if self._error is not None:
                raise RuntimeError(str(self._error))
            if self._stop_requested:
                raise RuntimeError("Servo dispatcher is stopping")
            if self._thread is None:
                raise RuntimeError("Servo dispatcher has not started")
            if self._pending is not None:
                self._dropped_commands += 1
            self._pending = dict(pulses)
            self._condition.notify_all()

    send = send_cycle

    def neutral(self):
        self.send_cycle(NEUTRAL)

    def check_health(self, now=None):
        del now
        with self._condition:
            if self._error is not None:
                raise RuntimeError(str(self._error))
            if self._thread is None or not self._thread.is_alive():
                raise RuntimeError("Servo dispatcher is not running")

    def _run(self):
        next_cycle_at = self.clock()
        try:
            while True:
                with self._condition:
                    if self._pending is None and not self._stop_requested:
                        self._condition.wait(timeout=0.1)
                    if self._stop_requested:
                        pulses = dict(NEUTRAL)
                        final_cycle = True
                        self._pending = None
                    elif self._pending is not None:
                        pulses = self._pending
                        final_cycle = False
                        self._pending = None
                        if pulses == self._last_applied:
                            pulses = None
                        else:
                            remaining = next_cycle_at - self.clock()
                            if remaining > 0:
                                self._pending = pulses
                                self._condition.wait(timeout=remaining)
                                continue
                    else:
                        pulses = None
                        final_cycle = False
                self.controller.check_health(now=self.clock())
                if pulses is None:
                    continue
                self.controller.send_cycle(pulses, now=self.clock())
                with self._condition:
                    self._last_applied = dict(pulses)
                next_cycle_at = self.clock() + self.min_cycle_interval
                if final_cycle:
                    return
        except Exception as error:
            try:
                self.controller.send_cycle(NEUTRAL, now=self.clock())
                with self._condition:
                    self._last_applied = dict(NEUTRAL)
            except Exception:
                pass
            with self._condition:
                self._error = error
                self._condition.notify_all()
        finally:
            self.controller.close()

    def close(self, timeout=5.0):
        with self._condition:
            if self._thread is None:
                self.controller.close()
                return
            self._stop_requested = True
            self._pending = None
            self._condition.notify_all()
            thread = self._thread
        thread.join(timeout=max(0.0, timeout))
        if thread.is_alive():
            self.controller.close()
            thread.join(timeout=0.2)
            with self._condition:
                if self._error is None:
                    self._error = RuntimeError(
                        "Servo dispatcher did not stop before timeout")
