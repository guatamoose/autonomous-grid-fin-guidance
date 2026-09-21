"""Local, time-limited visible bouncing-target bench simulation."""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bench_ball_sim import (NEUTRAL, ServoLink, VirtualScene, bounded_pulses_for,
                            validate_bench_cap)
from camera_zones import decide


def make_frame(scene, settings, max_offset):
    target = scene.target_center()
    target = (min(639, max(0, target[0])), min(479, max(0, target[1])))
    decision = decide(target, (640, 480), max_tested_us=max_offset)
    pulses = bounded_pulses_for(decision, settings)
    return {
        "ball": {"x": round(target[0]), "y": round(target[1])},
        "requested_us": decision.requested_us,
        "pulses": {str(channel): pulse for channel, pulse in pulses.items()},
    }


def run_session(link, publish, stop_event, duration=20, max_offset=400):
    """Command each published frame, with a finite run and neutral cleanup."""
    validate_bench_cap(max_offset)
    if not 0 < duration <= 30:
        raise ValueError("Live bench run must last 1–30 seconds")
    scene = VirtualScene()
    started = last = time.monotonic()
    try:
        link.send(NEUTRAL)
        while not stop_event.is_set() and time.monotonic() - started < duration:
            now = time.monotonic()
            frame = make_frame(scene, link.settings, max_offset)
            pulses = {int(channel): pulse for channel, pulse in frame["pulses"].items()}
            link.send(pulses)
            publish(frame)
            scene.advance(max(now - last, 0.05), NEUTRAL[8] - pulses[8],
                          pulses[7] - NEUTRAL[7])
            last = now
            stop_event.wait(0.05)
    finally:
        try:
            link.send(NEUTRAL)
        finally:
            link.close()


class SessionManager:
    def __init__(self, port="COM18", baud=115200, duration=20, max_offset=400):
        self.port = port
        self.baud = baud
        self.duration = duration
        self.max_offset = max_offset
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.state = {
            "status": "idle", "ball": {"x": 470, "y": 130},
            "requested_us": 0,
            "pulses": {str(channel): pulse for channel, pulse in NEUTRAL.items()},
            "elapsed": 0, "error": "",
        }
        self.thread = None

    def snapshot(self):
        with self.lock:
            return dict(self.state, ball=dict(self.state["ball"]),
                        pulses=dict(self.state["pulses"]))

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.stop_event = threading.Event()
            self.state.update(status="connecting", error="", elapsed=0)
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            return True

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.state["status"] in ("connecting", "running"):
                self.state["status"] = "stopping"

    def _worker(self):
        started = time.monotonic()

        def publish(frame):
            with self.lock:
                self.state.update(frame)
                self.state["status"] = "running"
                self.state["elapsed"] = round(time.monotonic() - started, 1)

        try:
            link = ServoLink(self.port, self.baud, self.max_offset)
            run_session(link, publish, self.stop_event,
                        self.duration, self.max_offset)
            with self.lock:
                self.state.update(
                    status="complete", requested_us=0,
                    pulses={str(channel): pulse for channel, pulse in NEUTRAL.items()},
                    elapsed=round(time.monotonic() - started, 1),
                )
        except Exception as exc:
            with self.lock:
                self.state.update(status="error", error=f"{type(exc).__name__}: {exc}")


def make_handler(manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def send_data(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = Path(__file__).with_suffix(".html").read_bytes()
                self.send_data(body, "text/html; charset=utf-8")
            elif self.path == "/state":
                body = json.dumps(manager.snapshot()).encode("utf-8")
                self.send_data(body, "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/start":
                started = manager.start()
                status = 200 if started else 409
            elif self.path == "/stop":
                manager.stop()
                status = 200
            else:
                self.send_error(404)
                return
            body = json.dumps(manager.snapshot()).encode("utf-8")
            self.send_data(body, "application/json", status)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM18", help="Flight controller serial port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--http-port", type=int, default=8765)
    args = parser.parse_args()
    manager = SessionManager(port=args.port, baud=args.baud)
    server = ThreadingHTTPServer(("127.0.0.1", args.http_port),
                                 make_handler(manager))
    print(f"Visible bench simulation: http://127.0.0.1:{args.http_port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        manager.stop()
        if manager.thread:
            manager.thread.join(timeout=10)
        server.server_close()


if __name__ == "__main__":
    main()
