"""Bounded bouncing-target servo bench test (no real camera or landing logic).

Default mode only prints virtual commands. --enable-servos requires a live,
disarmed ArduPilot link and checks the four configured neutral/limit values.
Real outputs are capped by --max-offset and the controller's live limits.
"""

import argparse
import time

from camera_zones import decide
from servo_controller import (NEUTRAL, ServoLink, bounded_pulses_for,
                              expected_settings, pulses_for,
                              validate_bench_cap, validate_command,
                              validate_settings)


class VirtualScene:
    def __init__(self):
        self.ball_x, self.ball_y = 150.0, -110.0
        self.ball_vx, self.ball_vy = -92.0, 73.0
        self.camera_x = self.camera_y = 0.0
        self.camera_vx = self.camera_vy = 0.0

    def target_center(self):
        return 320 + self.ball_x - self.camera_x, 240 + self.ball_y - self.camera_y

    def advance(self, seconds, nose_x_us, nose_y_us):
        self.ball_x += self.ball_vx * seconds
        self.ball_y += self.ball_vy * seconds
        if self.ball_x > 260:
            self.ball_x, self.ball_vx = 260, -abs(self.ball_vx)
        elif self.ball_x < -260:
            self.ball_x, self.ball_vx = -260, abs(self.ball_vx)
        if self.ball_y > 200:
            self.ball_y, self.ball_vy = 200, -abs(self.ball_vy)
        elif self.ball_y < -200:
            self.ball_y, self.ball_vy = -200, abs(self.ball_vy)
        # Arcade camera response: screen-space motion only, not rocket physics.
        target_vx = nose_x_us * 0.45
        target_vy = -nose_y_us * 0.45
        alpha = min(1.0, seconds * 5)
        self.camera_vx += (target_vx - self.camera_vx) * alpha
        self.camera_vy += (target_vy - self.camera_vy) * alpha
        self.camera_x += self.camera_vx * seconds
        self.camera_y += self.camera_vy * seconds


def run(duration, port, baud, enable_servos, max_offset=200):
    if not 0 < duration <= 30:
        raise ValueError("Bench simulation duration must be 1–30 seconds")
    validate_bench_cap(max_offset)
    scene = VirtualScene()
    link = ServoLink(port, baud, max_offset) if enable_servos else None
    settings = link.settings if link else expected_settings()
    started = time.monotonic()
    last = started
    try:
        if link:
            link.send(NEUTRAL)
        while time.monotonic() - started < duration:
            now = time.monotonic()
            dt = min(now - last, 0.5)
            last = now
            target = scene.target_center()
            # Keep the simulated ball within the camera field.
            target = (min(639, max(0, target[0])), min(479, max(0, target[1])))
            decision = decide(target, (640, 480), max_tested_us=max_offset)
            pulses = bounded_pulses_for(decision, settings)
            if link:
                link.send(pulses)
            print(f"t={now-started:4.1f}s ball=({target[0]:.0f},{target[1]:.0f}) "
                  f"zone={decision.requested_us} applied={decision.safe_us} "
                  f"S7={pulses[7]} S8={pulses[8]} S9={pulses[9]} S10={pulses[10]}",
                  flush=True)
            scene.advance(max(dt, 0.2), NEUTRAL[8] - pulses[8],
                          pulses[7] - NEUTRAL[7])
            time.sleep(0.2)
    finally:
        if link:
            try:
                link.send(NEUTRAL)
                print("All four outputs returned to neutral", flush=True)
            finally:
                link.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--port", default="/dev/serial0")
    parser.add_argument("--baud", type=int, default=57600)
    parser.add_argument("--enable-servos", action="store_true")
    parser.add_argument("--max-offset", type=int, choices=(200, 300, 400), default=200)
    args = parser.parse_args()
    run(args.duration, args.port, args.baud, args.enable_servos, args.max_offset)


if __name__ == "__main__":
    main()
