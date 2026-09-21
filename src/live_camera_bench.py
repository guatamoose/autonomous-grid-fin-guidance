"""Private camera preview with a finite, disarmed grid-fin bench run."""

import argparse
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bench_ball_sim import NEUTRAL, ServoLink, bounded_pulses_for, validate_bench_cap
from camera_zone_preview import open_camera, overlay_zones
from camera_zones import decide
from orange_pad import detect_orange_pad


def command_for_target(target, frame_size, settings, max_offset):
    decision = decide(target, frame_size, max_tested_us=max_offset)
    return bounded_pulses_for(decision, settings)


def command_for_sample(sample, now, settings, max_offset):
    target, frame_size, captured_at = sample
    if now - captured_at > 0.6:
        target = None
    return command_for_target(target, frame_size, settings, max_offset)


def mjpeg_part(jpeg):
    return (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n")


def run_camera_session(link, sample, stop_event, duration=20, max_offset=200,
                       publish=lambda pulses: None):
    validate_bench_cap(max_offset)
    if not 0 < duration <= 30:
        raise ValueError("Bench run must last 1–30 seconds")
    started = time.monotonic()
    try:
        link.send(NEUTRAL)
        while not stop_event.is_set() and time.monotonic() - started < duration:
            pulses = command_for_sample(sample(), time.monotonic(),
                                        link.settings, max_offset)
            link.send(pulses)
            publish(pulses)
            stop_event.wait(0.1)
    finally:
        try:
            link.send(NEUTRAL)
            publish(NEUTRAL)
        finally:
            link.close()


class BenchServer:
    def __init__(self, camera, port="/dev/serial0", baud=57600,
                 duration=20, max_offset=200, channel_order="BGR"):
        self.camera = camera
        self.port, self.baud = port, baud
        self.duration, self.max_offset = duration, max_offset
        self.channel_order = channel_order
        self.lock = threading.Lock()
        self.camera_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.sample = (None, (640, 480), 0.0)
        self.status = "idle"
        self.error = ""
        self.pulses = NEUTRAL.copy()
        self.frame_count = 0
        self.last_frame_at = 0.0
        self.fps = 0.0

    def frame(self):
        with self.camera_lock:
            frame = self.camera.capture_array()
        detection = detect_orange_pad(frame, channel_order=self.channel_order,
                                      sample_step=8)
        now = time.monotonic()
        target = detection.center if detection else None
        with self.lock:
            self.sample = (target, (frame.shape[1], frame.shape[0]), now)
            if self.last_frame_at:
                measured = 1 / max(0.001, now - self.last_frame_at)
                self.fps = measured if not self.fps else 0.7*self.fps + 0.3*measured
            self.last_frame_at = now
            self.frame_count += 1
            status = self.status
        footer = f"{status.upper()} | {self.fps:.1f} fps | bench only"
        image = overlay_zones(frame, self.channel_order, detection, footer)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=75)
        return buffer.getvalue()

    def get_sample(self):
        with self.lock:
            return self.sample

    def snapshot(self):
        with self.lock:
            return {"status": self.status, "error": self.error,
                    "target": self.sample[0], "fps": round(self.fps, 1),
                    "pulses": {str(k): v for k, v in self.pulses.items()}}

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.stop_event = threading.Event()
            self.status = "connecting"
            self.error = ""
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
            return True

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.status in ("running", "connecting"):
                self.status = "stopping"

    def _worker(self):
        def publish(pulses):
            with self.lock:
                self.pulses = dict(pulses)
                if self.status == "connecting":
                    self.status = "running"
        try:
            link = ServoLink(self.port, self.baud, self.max_offset)
            run_camera_session(link, self.get_sample, self.stop_event,
                               self.duration, self.max_offset, publish)
            with self.lock:
                self.status = "complete"
        except Exception as exc:
            with self.lock:
                self.status = "error"
                self.error = f"{type(exc).__name__}: {exc}"


PAGE = '''<!doctype html><meta name="viewport" content="width=device-width">
<title>Rocket camera bench test</title>
<style>body{font:16px system-ui;background:#161a20;color:white;margin:1em;max-width:850px}
img{width:100%;height:auto}button{font:inherit;padding:.6em 1em;margin-right:.5em}
#status{font-weight:bold}</style>
<h1>Rocket camera bench test</h1>
<p>Disarmed, 20-second bench run. Keep the rocket restrained and ignition disconnected.</p>
<p><button id="start">Start fin test</button><button id="stop">Stop and neutral</button>
<span id="status">idle</span></p>
<img id="frame" src="/stream.mjpg" alt="Live camera with pad and zones">
<p id="values"></p>
<script>
async function refresh(){
 try{const s=await (await fetch('/state')).json();
 document.getElementById('status').textContent=s.status+(s.error?' — '+s.error:'');
 document.getElementById('values').textContent=
   'Pad: '+(s.target||'not seen')+' | '+s.fps+' fps | S7 '+s.pulses['7']+
   '  S8 '+s.pulses['8']+'  S9 '+s.pulses['9']+'  S10 '+s.pulses['10'];}catch(e){}
}
document.getElementById('start').onclick=()=>fetch('/start',{method:'POST'}).then(refresh);
document.getElementById('stop').onclick=()=>fetch('/stop',{method:'POST'}).then(refresh);
setInterval(refresh,500);refresh();
</script>'''.encode("utf-8")


def handler_for(manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def respond(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.respond(PAGE, "text/html; charset=utf-8")
            elif self.path == "/stream.mjpg":
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.connection.settimeout(3)
                try:
                    while True:
                        self.wfile.write(mjpeg_part(manager.frame()))
                        self.wfile.flush()
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
            elif self.path.startswith("/frame.jpg"):
                self.respond(manager.frame(), "image/jpeg")
            elif self.path == "/state":
                self.respond(json.dumps(manager.snapshot()).encode(), "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path == "/start":
                status = 200 if manager.start() else 409
            elif self.path == "/stop":
                manager.stop()
                status = 200
            else:
                self.send_error(404)
                return
            self.respond(json.dumps(manager.snapshot()).encode(),
                         "application/json", status)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-port", type=int, default=8766)
    parser.add_argument("--max-offset", type=int, choices=(200, 300, 400), default=200)
    parser.add_argument("--duration", type=float, default=20)
    args = parser.parse_args()
    camera = open_camera()
    manager = BenchServer(camera, max_offset=args.max_offset,
                          duration=args.duration)
    server = ThreadingHTTPServer(("127.0.0.1", args.http_port), handler_for(manager))
    server.daemon_threads = True
    print(f"Camera bench: http://127.0.0.1:{args.http_port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        manager.stop()
        if manager.thread:
            manager.thread.join(timeout=10)
        server.server_close()
        camera.stop()
        camera.close()


if __name__ == "__main__":
    main()
