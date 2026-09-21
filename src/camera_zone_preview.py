"""Show camera-center steering zones and orange-pad detection without servos.

On the Raspberry Pi, use --snapshot FILE for one marked frame or --serve for
a simple browser preview. No fin commands are sent.
"""

import argparse
import io
import time
from dataclasses import dataclass
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from PIL import Image, ImageDraw

from camera_zones import DEAD_ZONE_RADIUS, RING_RADII, RING_REQUESTS_US, decide
from orange_pad import detect_orange_pad

_UNSET = object()


@dataclass(frozen=True)
class OverlayTelemetry:
    state: str
    acquire_count: int
    requested_us: int
    direction: str
    pulses: dict[int, int]
    neutrals: dict[int, int]
    observe_only: bool
    fps: float
    recording: str
    timestamp: str


def build_overlay_lines(telemetry):
    if telemetry.state in ("acquiring", "locked"):
        state = f"{telemetry.state.upper()} {telemetry.acquire_count}/3"
    else:
        state = telemetry.state.upper()
    motion = " ".join(
        f"S{channel} {telemetry.pulses[channel]} "
        f"({telemetry.pulses[channel] - telemetry.neutrals[channel]:+d})"
        for channel in (7, 8, 9, 10))
    mode = "OBSERVE ONLY" if telemetry.observe_only else "LIVE"
    return (
        f"{state} | {telemetry.direction} | "
        f"request {telemetry.requested_us} us",
        f"{motion} | {mode}",
        f"{telemetry.fps:.1f} fps | REC {telemetry.recording} | "
        f"{telemetry.timestamp}",
    )


@lru_cache(maxsize=4)
def _static_zone_overlay(width, height):
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = width / 2, height / 2
    radius = min(width, height) / 2
    for fraction, amount in zip(RING_RADII, RING_REQUESTS_US):
        r = radius * fraction
        color = (70, 190, 255)
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=color, width=2)
        draw.text((cx+r+5, cy-10), f"{round(fraction*100)}%: {amount}",
                  fill=(255, 255, 255), stroke_width=2,
                  stroke_fill=(0, 0, 0))

    r = radius * DEAD_ZONE_RADIUS
    draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(80, 240, 120), width=3)
    draw.line((cx-6, cy, cx+6, cy), fill=(80, 240, 120), width=2)
    draw.line((cx, cy-6, cx, cy+6), fill=(80, 240, 120), width=2)
    return overlay


def overlay_zones(frame, channel_order="RGB", detection=_UNSET, footer=None,
                  telemetry=None):
    if detection is _UNSET:
        detection = detect_orange_pad(frame, channel_order=channel_order)
    rgb_frame = frame if channel_order == "RGB" else frame[:, :, ::-1].copy()
    image = Image.fromarray(rgb_frame).convert("RGB")
    width, height = image.size
    cx, cy = width / 2, height / 2
    image.paste(_static_zone_overlay(width, height), (0, 0),
                _static_zone_overlay(width, height))
    draw = ImageDraw.Draw(image)
    target = detection.center if detection else None
    choice = decide(target, (width, height))
    if detection:
        x0, y0, x1, y1 = detection.bbox
        draw.rectangle((x0, y0, x1, y1), outline=(255, 160, 30), width=3)
        px, py = detection.center
        draw.line((cx, cy, px, py), fill=(255, 160, 30), width=2)
        draw.line((px-8, py, px+8, py), fill=(255, 255, 255), width=2)
        draw.line((px, py-8, px, py+8), fill=(255, 255, 255), width=2)
        label = (f"ORANGE PAD ({px},{py}) | zone {choice.requested_us} us | "
                 f"area {detection.area_fraction:.1%}")
    else:
        label = "NO ORANGE PAD | neutral"
    draw.rectangle((0, 0, width, 22), fill=(0, 0, 0))
    draw.text((8, 5), label, fill=(255, 255, 255))
    if telemetry is not None:
        footer_lines = build_overlay_lines(telemetry)
    elif isinstance(footer, (tuple, list)):
        footer_lines = tuple(footer)
    else:
        footer_lines = (footer or "PREVIEW ONLY | no servo output",)
    line_height = 15
    band_height = len(footer_lines) * line_height + 7
    draw.rectangle((0, height-band_height, width, height), fill=(0, 0, 0))
    for index, line in enumerate(footer_lines):
        draw.text((8, height-band_height+4+index*line_height), line,
                  fill=(255, 255, 255))
    return image


def open_camera():
    from picamera2 import Picamera2

    camera = Picamera2()
    config = camera.create_preview_configuration(
        main={"size": (640, 480), "format": "RGB888"}
    )
    camera.configure(config)
    camera.start()
    time.sleep(1)
    return camera


def serve(camera, host, port, channel_order):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/frame.jpg"):
                image = overlay_zones(camera.capture_array(), channel_order)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=80)
                payload = buffer.getvalue()
                kind = "image/jpeg"
            elif self.path == "/":
                payload = (
                    b'<!doctype html><meta name="viewport" content="width=device-width">'
                    b'<title>Rocket orange-pad preview</title>'
                    b'<style>body{font:16px system-ui;background:#161a20;color:white;margin:1em}'
                    b'img{width:min(100%,800px);height:auto}</style>'
                    b'<h1>Rocket orange-pad preview</h1>'
                    b'<p>Orange rectangle detection and camera zones. Servo output is off.</p>'
                    b'<img id="frame" src="/frame.jpg" alt="Camera view with concentric steering zones">'
                    b'<script>setInterval(()=>{document.getElementById("frame").src=' 
                    b'"/frame.jpg?t="+Date.now()},150)</script>'
                )
                kind = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer((host, port), Handler)
    print(f"Camera zone preview: http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path, metavar="FILE")
    mode.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--channel-order", choices=("RGB", "BGR"), default="RGB")
    args = parser.parse_args()

    camera = open_camera()
    try:
        if args.snapshot:
            overlay_zones(camera.capture_array(), args.channel_order).save(args.snapshot)
            print(args.snapshot)
        else:
            serve(camera, args.host, args.port, args.channel_order)
    finally:
        camera.stop()
        camera.close()


if __name__ == "__main__":
    main()
