import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camera_zones import decide
from servo_controller import (NEUTRAL, AsyncServoDispatcher, MavlinkServoController,
                              bounded_pulses_for, expected_settings)


class FakeMavlink:
    MAV_MODE_FLAG_SAFETY_ARMED = 128
    MAV_CMD_DO_SET_SERVO = 183
    MAV_CMD_COMPONENT_ARM_DISARM = 400
    MAV_RESULT_ACCEPTED = 0
    MAV_RESULT_DENIED = 2


class FakeMavutil:
    mavlink = FakeMavlink


class FakeMessage:
    def __init__(self, kind, **values):
        self.kind = kind
        self.__dict__.update(values)

    def get_type(self):
        return self.kind


class FakeConnection:
    target_system = 1

    def __init__(self, parameters=None, armed=False, reject_channel=None,
                 missing_ack_channel=None, record_receives=False,
                 dropped_param_requests=None, dropped_ack_requests=None):
        self.parameters = parameters or flat_settings()
        self.armed = armed
        self.reject_channel = reject_channel
        self.missing_ack_channel = missing_ack_channel
        self.record_receives = record_receives
        self.dropped_param_requests = dict(dropped_param_requests or {})
        self.dropped_ack_requests = dict(dropped_ack_requests or {})
        self.confirmations = []
        self.pending = []
        self.nonblocking = []
        self.events = []
        self.mav = self

    def wait_heartbeat(self, timeout):
        self.events.append(("wait_heartbeat", timeout))
        return FakeMessage("HEARTBEAT", base_mode=(128 if self.armed else 0))

    def param_request_read_send(self, target_system, component, name, index):
        key = name.decode("ascii")
        self.events.append(("param", key))
        if self.dropped_param_requests.get(key, 0) > 0:
            self.dropped_param_requests[key] -= 1
            return
        self.pending.append(FakeMessage("PARAM_VALUE", param_id=key,
                                        param_value=self.parameters[key]))

    def command_long_send(self, target_system, component, command,
                          confirmation, channel, pwm, *unused):
        self.events.append(("command", int(channel), int(pwm)))
        self.confirmations.append((int(channel), int(confirmation)))
        if self.dropped_ack_requests.get(channel, 0) > 0:
            self.dropped_ack_requests[channel] -= 1
            return
        if channel != self.missing_ack_channel:
            result = (FakeMavlink.MAV_RESULT_DENIED
                      if channel == self.reject_channel
                      else FakeMavlink.MAV_RESULT_ACCEPTED)
            self.pending.append(FakeMessage("COMMAND_ACK", command=command,
                                            result=result))

    def recv_match(self, blocking=False, timeout=None):
        if self.record_receives:
            self.events.append(("recv", blocking, timeout))
        if self.pending:
            return self.pending.pop(0)
        if not blocking and self.nonblocking:
            return self.nonblocking.pop(0)
        return None

    def close(self):
        self.events.append(("close",))


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class TickingClock:
    def __init__(self, step=0.1):
        self.now = 0.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


def flat_settings():
    values = {}
    for channel, setting in expected_settings().items():
        for field, value in setting.items():
            values[f"SERVO{channel}_{field.upper()}"] = value
    return values


def connected_controller(connection=None, clock=lambda: 0.0,
                         require_disarmed=False):
    connection = connection or FakeConnection()
    controller = MavlinkServoController(
        "fake", 57600, 400, connection=connection,
        mavutil_module=FakeMavutil, clock=clock,
        require_disarmed=require_disarmed)
    controller.connect()
    return controller


class ServoControllerTests(unittest.TestCase):
    def test_connect_reads_exact_saved_settings(self):
        controller = connected_controller()
        self.assertEqual(controller.settings, expected_settings())

    def test_autonomous_connection_allows_armed_heartbeat(self):
        controller = connected_controller(FakeConnection(armed=True))
        self.assertTrue(controller.armed)

    def test_bench_connection_rejects_armed_heartbeat(self):
        with self.assertRaisesRegex(RuntimeError, "armed"):
            connected_controller(FakeConnection(armed=True),
                                 require_disarmed=True)

    def test_send_cycle_sends_all_four_validated_commands(self):
        connection = FakeConnection()
        controller = connected_controller(connection)
        before = len(connection.events)
        controller.send_cycle(NEUTRAL, now=0.1)
        commands = [event for event in connection.events[before:]
                    if event[0] == "command"]
        self.assertEqual(commands, [
            ("command", 7, 1505), ("command", 8, 1460),
            ("command", 9, 1370), ("command", 10, 1200)])

    def test_send_cycle_waits_for_each_ack_before_next_command(self):
        connection = FakeConnection(record_receives=True)
        controller = connected_controller(connection)
        connection.events.clear()
        controller.send_cycle(NEUTRAL, now=0.1)
        self.assertEqual(
            [event[0] for event in connection.events],
            ["command", "recv", "command", "recv",
             "command", "recv", "command", "recv"])

    def test_interleaved_heartbeat_and_unrelated_ack_do_not_count(self):
        connection = FakeConnection()
        controller = connected_controller(connection)
        connection.pending.extend([
            FakeMessage("HEARTBEAT", base_mode=0),
            FakeMessage(
                "COMMAND_ACK",
                command=FakeMavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                result=FakeMavlink.MAV_RESULT_ACCEPTED),
        ])
        controller.send_cycle(NEUTRAL)
        commands = [event for event in connection.events
                    if event[0] == "command"]
        self.assertEqual(len(commands), 4)

    def test_missing_servo_ack_identifies_channel(self):
        connection = FakeConnection(missing_ack_channel=10)
        controller = connected_controller(connection, clock=TickingClock())
        with self.assertRaisesRegex(RuntimeError, "S10"):
            controller.send_cycle(NEUTRAL)

    def test_rejected_servo_ack_raises(self):
        controller = connected_controller(FakeConnection(reject_channel=9))
        with self.assertRaisesRegex(RuntimeError, "S9 command rejected"):
            controller.send_cycle(NEUTRAL, now=0.1)

    def test_timed_out_servo_command_is_retried_with_confirmation(self):
        connection = FakeConnection(dropped_ack_requests={10: 1})
        controller = connected_controller(
            connection, clock=TickingClock(step=0.05))
        controller.send_cycle(NEUTRAL)
        confirmations = [confirmation for channel, confirmation
                         in connection.confirmations if channel == 10]
        self.assertEqual(confirmations, [0, 1])

    def test_one_second_heartbeat_jitter_is_accepted(self):
        controller = connected_controller()
        controller.check_health(now=1.1)

    def test_heartbeat_older_than_two_and_a_half_seconds_fails_health_check(self):
        controller = connected_controller()
        with self.assertRaisesRegex(RuntimeError, "heartbeat"):
            controller.check_health(now=2.51)

    def test_periodic_parameter_change_fails_health_check(self):
        connection = FakeConnection()
        clock = FakeClock()
        controller = connected_controller(connection, clock=clock)
        connection.parameters["SERVO7_FUNCTION"] = 1
        clock.now = 1.1
        connection.nonblocking.append(FakeMessage("HEARTBEAT", base_mode=0))
        with self.assertRaisesRegex(ValueError, "S7"):
            controller.check_health(now=1.1)

    def test_health_check_reads_one_parameter_per_interval(self):
        connection = FakeConnection()
        clock = FakeClock()
        controller = connected_controller(connection, clock=clock)
        connection.events.clear()
        connection.nonblocking.append(FakeMessage("HEARTBEAT", base_mode=0))
        clock.now = 1.1
        controller.check_health(now=1.1)
        self.assertEqual(
            [event for event in connection.events if event[0] == "param"],
            [("param", "SERVO7_FUNCTION")])

    def test_parameter_read_retries_a_dropped_request(self):
        connection = FakeConnection(
            dropped_param_requests={"SERVO7_FUNCTION": 1})
        controller = connected_controller(
            connection, clock=TickingClock(step=0.05))
        self.assertEqual(controller.settings, expected_settings())
        requests = [event for event in connection.events
                    if event == ("param", "SERVO7_FUNCTION")]
        self.assertEqual(len(requests), 2)

    def test_close_attempts_neutral_before_serial_close(self):
        connection = FakeConnection()
        controller = connected_controller(connection)
        controller.close()
        self.assertEqual(connection.events[-5:], [
            ("command", 7, 1505), ("command", 8, 1460),
            ("command", 9, 1370), ("command", 10, 1200),
            ("close",)])

    def test_diagonal_request_scales_both_axes_to_saved_limits(self):
        decision = decide((0, 0), (640, 480), max_tested_us=400)
        pulses = bounded_pulses_for(decision, expected_settings())
        self.assertTrue(all(expected_settings()[ch]["min"] <= pwm <=
                            expected_settings()[ch]["max"]
                            for ch, pwm in pulses.items()))
        requested_x = abs(decision.safe_nose_x_us)
        requested_y = abs(decision.safe_nose_y_us)
        applied_x = abs(pulses[8] - NEUTRAL[8])
        applied_y = abs(pulses[7] - NEUTRAL[7])
        self.assertAlmostEqual(applied_x / requested_x,
                               applied_y / requested_y, delta=0.01)

    def test_cardinal_outer_zone_reaches_full_400_offset(self):
        horizontal = bounded_pulses_for(
            decide((639, 240), (640, 480), max_tested_us=400),
            expected_settings())
        vertical = bounded_pulses_for(
            decide((320, 0), (640, 480), max_tested_us=400),
            expected_settings())
        self.assertEqual(horizontal[8], NEUTRAL[8] - 400)
        self.assertEqual(horizontal[9], NEUTRAL[9] + 400)
        self.assertEqual(vertical[7], NEUTRAL[7] + 400)
        self.assertEqual(vertical[10], NEUTRAL[10] - 400)


class BlockingServoController:
    def __init__(self):
        self.settings = expected_settings()
        self.sent = []
        self.health_checks = 0
        self.closed = False
        self.started = threading.Event()
        self.release = threading.Event()

    def check_health(self, now=None):
        self.health_checks += 1

    def send_cycle(self, pulses, now=None):
        self.sent.append(dict(pulses))
        self.started.set()
        self.release.wait(timeout=1.0)

    def close(self):
        self.closed = True


class FailingServoController(BlockingServoController):
    def send_cycle(self, pulses, now=None):
        self.sent.append(dict(pulses))
        if pulses != NEUTRAL:
            raise RuntimeError("serial acknowledgement failed")


class ImmediateServoController(BlockingServoController):
    def __init__(self):
        super().__init__()
        self.sent_at = []

    def send_cycle(self, pulses, now=None):
        self.sent.append(dict(pulses))
        self.sent_at.append(time.monotonic())
        self.started.set()


class AsyncServoDispatcherTests(unittest.TestCase):
    def test_publish_is_nonblocking_and_replaces_stale_pending_command(self):
        raw = BlockingServoController()
        dispatcher = AsyncServoDispatcher(raw).start()
        first = dict(NEUTRAL)
        first[7] += 100
        second = dict(NEUTRAL)
        second[8] -= 200
        latest = dict(NEUTRAL)
        latest[9] += 300

        started = time.monotonic()
        dispatcher.send_cycle(first)
        self.assertLess(time.monotonic() - started, 0.05)
        self.assertTrue(raw.started.wait(timeout=0.5))
        dispatcher.send_cycle(second)
        dispatcher.send_cycle(latest)
        raw.release.set()

        deadline = time.monotonic() + 0.5
        while len(raw.sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        dispatcher.close()

        self.assertEqual(raw.sent[0], first)
        self.assertEqual(raw.sent[1], latest)
        self.assertEqual(raw.sent[-1], NEUTRAL)
        self.assertGreaterEqual(dispatcher.dropped_commands, 1)
        self.assertTrue(raw.closed)

    def test_unchanged_commands_are_not_resent(self):
        raw = ImmediateServoController()
        dispatcher = AsyncServoDispatcher(raw).start()
        command = dict(NEUTRAL)
        command[8] -= 100
        dispatcher.send_cycle(command)
        self.assertTrue(raw.started.wait(timeout=0.5))
        dispatcher.send_cycle(command)
        time.sleep(0.2)
        self.assertEqual(raw.sent, [command])
        dispatcher.close()

    def test_changed_commands_are_limited_to_eight_hz(self):
        raw = ImmediateServoController()
        dispatcher = AsyncServoDispatcher(raw).start()
        first = dict(NEUTRAL)
        first[7] += 100
        second = dict(NEUTRAL)
        second[7] += 200
        dispatcher.send_cycle(first)
        deadline = time.monotonic() + 0.5
        while len(raw.sent) < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        dispatcher.send_cycle(second)
        deadline = time.monotonic() + 0.5
        while len(raw.sent) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertGreaterEqual(raw.sent_at[1] - raw.sent_at[0], 0.115)
        dispatcher.close()

    def test_worker_failure_is_reported_and_attempts_neutral(self):
        raw = FailingServoController()
        dispatcher = AsyncServoDispatcher(raw).start()
        command = dict(NEUTRAL)
        command[7] += 100
        dispatcher.send_cycle(command)

        deadline = time.monotonic() + 0.5
        while dispatcher.error is None and time.monotonic() < deadline:
            time.sleep(0.005)

        with self.assertRaisesRegex(RuntimeError, "serial acknowledgement failed"):
            dispatcher.check_health()
        dispatcher.close()
        self.assertEqual(raw.sent[-1], NEUTRAL)


if __name__ == "__main__":
    unittest.main()
