"""Read-only browser monitor for the autonomous guidance runtime."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PAGE = b"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width">
<title>Rocket guidance monitor</title>
<style>
body{font:16px system-ui;background:#111820;color:#eef;margin:1rem auto;max-width:900px}
h1{margin-bottom:.25rem}.card{background:#1c2733;padding:1rem;border-radius:.6rem;margin:.8rem 0}
img{display:block;width:100%;height:auto;border-radius:.4rem;background:#000}
#state{font-size:1.4rem;font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem}
button{background:#b83232;color:white;border:0;border-radius:.4rem;padding:.8rem 1.2rem;font-weight:700}
.warn{color:#ffca5c}code{color:#9fe1ff}
</style></head><body>
<h1>Rocket guidance monitor</h1>
<p>The guidance service runs independently of this page.</p>
<img src="/stream.mjpg" alt="Live camera view with guidance overlay">
<div class="card"><div id="state">STARTING</div><div id="detail"></div></div>
<div class="card grid" id="pulses"></div>
<div class="card"><button id="stop">Stop and neutral</button>
<p class="warn" id="message"></p></div>
<script>
const state=document.getElementById('state'),detail=document.getElementById('detail');
async function update(){try{const s=await (await fetch('/state',{cache:'no-store'})).json();
 let label=s.state.toUpperCase();if(s.state==='acquiring')label+=` ${s.acquire_count}/3`;
 state.textContent=label;detail.textContent=`ring ${s.requested_us} us | ${s.fps.toFixed(1)} fps`+
 ` | recording ${s.recording} | frames ${s.recording_frames} | dropped ${s.recording_dropped}`+
 (s.reason?` | ${s.reason}`:'')+(s.recording_error?` | REC ERROR: ${s.recording_error}`:'');
 document.getElementById('pulses').innerHTML=Object.entries(s.pulses).map(([k,v])=>`<div>S${k}: <code>${v}</code></div>`).join('');
}catch(e){detail.textContent='Monitor connection lost';}}
setInterval(update,250);update();
document.getElementById('stop').onclick=async()=>{if(!confirm('Stop guidance and return all fins to neutral?'))return;
 const r=await (await fetch('/stop',{method:'POST'})).json();document.getElementById('message').textContent=r.message;update();};
</script></body></html>"""


def make_monitor_server(runtime, host="127.0.0.1", port=8766):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, kind, payload):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE)
                return
            if self.path == "/state":
                payload = json.dumps(runtime.snapshot()).encode("utf-8")
                self._send(200, "application/json", payload)
                return
            if self.path == "/stream.mjpg":
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                last_sequence = -1
                try:
                    while True:
                        snapshot = runtime.frame_hub.latest()
                        if (snapshot is None or not snapshot.jpeg or
                                snapshot.sequence == last_sequence):
                            time.sleep(0.02)
                            continue
                        last_sequence = snapshot.sequence
                        header = (b"--frame\r\nContent-Type: image/jpeg\r\n" +
                                  f"Content-Length: {len(snapshot.jpeg)}\r\n\r\n".encode())
                        self.wfile.write(header)
                        self.wfile.write(snapshot.jpeg)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
                return
            self.send_error(404)

        def do_POST(self):
            if self.path != "/stop":
                self.send_error(404)
                return
            status = runtime.stop_and_neutral()
            payload = json.dumps({
                "state": status["state"],
                "message": ("Guidance is inhibited and all fins were commanded "
                            "to neutral. Restart the service to re-enable guidance."),
            }).encode("utf-8")
            self._send(200, "application/json", payload)

        def log_message(self, *unused):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
