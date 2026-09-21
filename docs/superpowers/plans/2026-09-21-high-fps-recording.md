# High-FPS Guidance and Evidence Recording Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustain 10–15 completed guidance frames per second while automatically retaining one hour of annotated H.264 video that shows landing-pad lock and actual S7–S10 commands.

**Architecture:** Pipeline each validated four-servo MAVLink batch before collecting its acknowledgements, then target a 15 FPS main loop. A capacity-one asynchronous recorder receives the same annotated JPEG used by the monitor and feeds a hardware H.264 FFmpeg process, so encoding and disk latency cannot block guidance.

**Tech Stack:** Python 3.13, `unittest`, Picamera2, Pillow, NumPy, pymavlink, FFmpeg `h264_v4l2m2m`, systemd

**Spec:** `docs/superpowers/specs/2026-09-21-high-fps-recording-design.md`

## Global Constraints

- Camera and recorded resolution remain 640×480.
- Main-loop target is 15 FPS; Pi acceptance range is 10–15 completed guidance FPS with recording active.
- Flight-controller link remains `/dev/serial0` at 57600 baud.
- S7–S10 functions remain 0 and endpoints remain S7 1105/1505/1905, S8 1060/1460/1860, S9 970/1370/1770, S10 800/1200/1600.
- Guidance retains three-frame acquisition, 3% ring hysteresis, a 5% dead zone, 0.5-second loss timeout, and a ±400 microsecond final cap.
- Each recorded frame shows rings, target lock, requested correction, actual S7–S10 PWM values, signed neutral offsets, observe-only/live state, measured FPS, recording state, and wall-clock time.
- Recording uses 640×480 H.264 MP4, 15 FPS, 2 Mbit/s, one-minute segments, and 60 completed-segment retention under `/home/pi/rocket/recordings`.
- Guidance must never wait for FFmpeg, recording disk I/O, or retention work.
- Recording faults are visible but do not stop guidance; camera, MAVLink, parameter, command, and guidance faults retain fail-neutral behavior.
- Deployment remains observe-only; this plan does not enable live fin movement.
- The workspace currently has no Git repository. Record passing commands in `work/verification-log.md`; if Git is initialized before execution, use the listed commits.

## Review Focus

- A burst containing heartbeats or unrelated acknowledgements must count only four accepted `MAV_CMD_DO_SET_SERVO` acknowledgements; Task 1 tests interleaving and timeout.
- FFmpeg backpressure or a full pipe must never block `GuidanceRuntime._step()`; Task 3 tests capacity-one replacement and a deliberately stalled process.
- A failed encoder, full disk, or retention exception must report `failed` while guidance frames continue; Tasks 3 and 4 test failure isolation.
- Service termination during an active segment must neutralize first and close FFmpeg with a bounded wait; Task 4 tests cleanup order and timeout.
- Retention across a reboot must preserve the newest active-looking file, keep 60 completed clips, ignore unrelated files, and avoid filename collisions; Task 3 tests all four cases.

---

### Task 1: Pipelined Four-Servo MAVLink Cycles

**Files:**
- Modify: `src/servo_controller.py`
- Modify: `tests/test_servo_controller.py`

**Interfaces:**
- Consumes: a connected pymavlink connection and `send_cycle(pulses: dict[int, int], now: float | None)`.
- Produces: `_wait_servo_acks(expected_count: int, timeout: float = 2.0) -> None`; `send_cycle()` emits all four commands before receiving acknowledgements.

- [ ] **Step 1: Write failing batch-order and acknowledgement tests**

Extend the fake connection with a shared event list and queued messages. Add:

```python
def test_send_cycle_pipelines_all_commands_before_reading_acks(self):
    controller = connected_fake_controller()
    controller.connection.queue_servo_acks(4)
    controller.send_cycle(NEUTRAL)
    events = controller.connection.events
    first_receive = next(i for i, event in enumerate(events)
                         if event[0] == "recv")
    self.assertEqual(
        [event[0] for event in events[:first_receive]],
        ["command", "command", "command", "command"])

def test_interleaved_heartbeat_and_unrelated_ack_do_not_count(self):
    controller = connected_fake_controller()
    controller.connection.messages.extend([
        heartbeat(), command_ack(MAV_CMD_COMPONENT_ARM_DISARM, ACCEPTED),
        *[command_ack(MAV_CMD_DO_SET_SERVO, ACCEPTED) for _ in range(4)],
    ])
    controller.send_cycle(NEUTRAL)
    self.assertEqual(len(controller.connection.commands), 4)

def test_missing_fourth_servo_ack_fails_cycle(self):
    controller = connected_fake_controller()
    controller.connection.queue_servo_acks(3)
    with self.assertRaisesRegex(RuntimeError, "3 of 4"):
        controller.send_cycle(NEUTRAL)

def test_rejected_batched_ack_fails_immediately(self):
    controller = connected_fake_controller()
    controller.connection.messages.extend([
        command_ack(MAV_CMD_DO_SET_SERVO, ACCEPTED),
        command_ack(MAV_CMD_DO_SET_SERVO, DENIED),
    ])
    with self.assertRaisesRegex(RuntimeError, "rejected"):
        controller.send_cycle(NEUTRAL)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_servo_controller -v
```

Expected: the batch-order test shows a receive between commands or `_wait_servo_acks` is missing; timeout/rejection messages do not match.

- [ ] **Step 3: Implement the bounded acknowledgement collector**

Replace per-channel `_wait_servo_ack()` use with:

```python
def _wait_servo_acks(self, expected_count, timeout=2.0):
    accepted = 0
    deadline = self.clock() + timeout
    while accepted < expected_count and self.clock() < deadline:
        msg = self.connection.recv_match(blocking=True, timeout=0.05)
        if msg and msg.get_type() == "HEARTBEAT":
            self._note_heartbeat(msg)
            continue
        if not msg or msg.get_type() != "COMMAND_ACK":
            continue
        if msg.command != self.mavutil.mavlink.MAV_CMD_DO_SET_SERVO:
            continue
        if msg.result != self.mavutil.mavlink.MAV_RESULT_ACCEPTED:
            raise RuntimeError(f"Servo command batch rejected: {msg.result}")
        accepted += 1
    if accepted != expected_count:
        raise RuntimeError(
            f"Servo command batch received {accepted} of {expected_count} acknowledgements")
```

After validating all pulses, `send_cycle()` sends S7, S8, S9, and S10 without receiving, then calls `_wait_servo_acks(4)` once.

- [ ] **Step 4: Run controller and runtime tests**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_servo_controller tests.test_autonomous_guidance -v
```

Expected: all tests pass, including existing validation, heartbeat, rejection, parameter, and neutral cleanup cases.

- [ ] **Step 5: Record the checkpoint**

Append the passing command and count to `work/verification-log.md`. If Git exists:

```bash
git add src/servo_controller.py tests/test_servo_controller.py work/verification-log.md
git commit -m "perf: pipeline grid-fin command acknowledgements"
```

---

### Task 2: Structured Overlay Telemetry

**Files:**
- Modify: `src/camera_zone_preview.py`
- Modify: `src/autonomous_guidance.py`
- Modify: `tests/test_camera_zone_preview.py`
- Modify: `tests/test_autonomous_guidance.py`

**Interfaces:**
- Consumes: guidance output, actual pulse dictionary, FPS, recorder status, and wall-clock timestamp.
- Produces: immutable `OverlayTelemetry`; `build_overlay_lines(telemetry: OverlayTelemetry) -> tuple[str, ...]`; `render_jpeg(..., telemetry: OverlayTelemetry) -> bytes`.

- [ ] **Step 1: Write failing telemetry-content tests**

Add a pure text test instead of fragile pixel matching:

```python
def test_overlay_lines_include_lock_and_signed_servo_movements():
    telemetry = OverlayTelemetry(
        state="locked", acquire_count=3, requested_us=300,
        direction="left-up", pulses={7: 1705, 8: 1260, 9: 1570, 10: 1000},
        neutrals=NEUTRAL, observe_only=False, fps=12.4,
        recording="active", timestamp="2026-09-21T05:12:03Z")
    lines = build_overlay_lines(telemetry)
    text = "\n".join(lines)
    self.assertIn("LOCKED 3/3", text)
    self.assertIn("left-up 300 us", text)
    self.assertIn("S7 1705 (+200)", text)
    self.assertIn("S10 1000 (-200)", text)
    self.assertIn("12.4 fps", text)
    self.assertIn("REC active", text)

def test_observe_only_overlay_distinguishes_request_from_actual_neutral():
    telemetry = observe_only_telemetry(requested_us=400)
    text = "\n".join(build_overlay_lines(telemetry))
    self.assertIn("request 400 us", text)
    self.assertIn("OBSERVE ONLY", text)
    self.assertIn("S7 1505 (+0)", text)
```

Add a renderer spy test that verifies `GuidanceRuntime` passes the same actual pulses published in `/state` into `OverlayTelemetry`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_camera_zone_preview tests.test_autonomous_guidance -v
```

Expected: import failure for `OverlayTelemetry` or missing structured telemetry argument.

- [ ] **Step 3: Implement the telemetry record and multiline overlay**

Add to `camera_zone_preview.py`:

```python
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
    lock = (f"{telemetry.state.upper()} {telemetry.acquire_count}/3"
            if telemetry.state == "acquiring" else telemetry.state.upper())
    motion = " ".join(
        f"S{ch} {telemetry.pulses[ch]} "
        f"({telemetry.pulses[ch] - telemetry.neutrals[ch]:+d})"
        for ch in (7, 8, 9, 10))
    mode = "OBSERVE ONLY" if telemetry.observe_only else "LIVE"
    return (
        f"{lock} | {telemetry.direction} | request {telemetry.requested_us} us",
        f"{motion} | {mode}",
        f"{telemetry.fps:.1f} fps | REC {telemetry.recording} | {telemetry.timestamp}",
    )
```

Expand the bottom overlay band to fit three lines. Keep the ring and target drawing unchanged. Add a pure direction helper that returns `center`, `left`, `right`, `up`, `down`, or diagonal combinations from the guidance output axes.

- [ ] **Step 4: Target a 15 FPS main-loop interval**

Add `target_fps=15.0` to `GuidanceRuntime.__init__`, validate it is positive, and set `self.loop_interval = 1.0 / target_fps`. Add CLI `--target-fps` and pass it into the runtime. Preserve deterministic injected clocks and sleepers in tests.

- [ ] **Step 5: Run overlay, runtime, and browser tests**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_camera_zone_preview tests.test_autonomous_guidance tests.test_guidance_web -v
```

Expected: all tests pass and existing ring geometry, target boxes, state publication, and monitor isolation remain unchanged.

- [ ] **Step 6: Record the checkpoint**

Append verification to `work/verification-log.md`. If Git exists:

```bash
git add src/camera_zone_preview.py src/autonomous_guidance.py tests/test_camera_zone_preview.py tests/test_autonomous_guidance.py work/verification-log.md
git commit -m "feat: add recorded guidance telemetry overlay"
```

---

### Task 3: Nonblocking Rolling H.264 Recorder

**Files:**
- Create: `src/guidance_recorder.py`
- Create: `tests/test_guidance_recorder.py`

**Interfaces:**
- Consumes: annotated JPEG bytes and their monotonic capture time.
- Produces: `RecorderStatus`; `RollingVideoRecorder.start()`; `publish(jpeg: bytes, captured_at: float) -> bool`; `status() -> RecorderStatus`; `close(timeout: float = 5.0)`; `prune_recordings(directory, keep_completed, active_path=None)`.

- [ ] **Step 1: Write failing capacity-one and failure-isolation tests**

Use a fake process whose stdin can stall or fail without creating threads that never exit:

```python
def test_publish_replaces_pending_frame_without_blocking():
    recorder = recorder_with_stalled_process()
    recorder.start()
    self.assertTrue(recorder.publish(b"frame-1", 1.0))
    started = time.monotonic()
    self.assertTrue(recorder.publish(b"frame-2", 1.1))
    self.assertLess(time.monotonic() - started, 0.02)
    self.assertEqual(recorder.status().dropped_frames, 1)

def test_encoder_failure_is_reported_without_raise_from_publish():
    recorder = recorder_with_process_that_exits(1)
    recorder.start()
    recorder.publish(b"jpeg", 1.0)
    wait_for(lambda: recorder.status().state == "failed")
    self.assertIn("FFmpeg exited", recorder.status().error)
    self.assertFalse(recorder.publish(b"next", 1.1))

def test_close_has_bounded_wait_then_terminates_process():
    process = process_that_never_exits()
    recorder = recorder_with(process)
    recorder.start()
    recorder.close(timeout=0.01)
    self.assertTrue(process.stdin.closed)
    self.assertTrue(process.terminate_called)
```

- [ ] **Step 2: Write failing FFmpeg-command and retention tests**

```python
def test_ffmpeg_command_uses_required_hardware_recording_settings():
    command = build_ffmpeg_command(Path("/recordings"), fps=15,
                                   bitrate=2_000_000, segment_seconds=60,
                                   session_token="a1b2")
    self.assertIn("h264_v4l2m2m", command)
    self.assertIn("2000000", command)
    self.assertIn("60", command)
    self.assertTrue(command[-1].endswith(
        "guidance-%Y%m%dT%H%M%SZ-a1b2.mp4"))

def test_retention_keeps_sixty_completed_plus_active_and_ignores_other_files():
    clips = create_timestamped_clips(65)
    unrelated = create_file("notes.txt")
    active = clips[-1]
    prune_recordings(temp_dir, keep_completed=60, active_path=active)
    remaining = sorted(temp_dir.glob("guidance-*.mp4"))
    self.assertEqual(remaining, clips[-61:])
    self.assertTrue(unrelated.exists())

def test_closed_recorder_prunes_to_exactly_sixty():
    clips = create_timestamped_clips(65)
    prune_recordings(temp_dir, keep_completed=60, active_path=None)
    self.assertEqual(sorted(temp_dir.glob("guidance-*.mp4")), clips[-60:])
```

Add a collision test asserting filenames include seconds and FFmpeg's strftime naming does not overwrite an existing clip.

- [ ] **Step 3: Run recorder tests and verify RED**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_guidance_recorder -v
```

Expected: import failure for `guidance_recorder`.

- [ ] **Step 4: Implement status, command construction, and retention**

Use:

```python
@dataclass(frozen=True)
class RecorderStatus:
    state: str
    current_clip: str | None = None
    frames_written: int = 0
    dropped_frames: int = 0
    error: str = ""

def build_ffmpeg_command(directory, fps, bitrate, segment_seconds,
                         session_token):
    pattern = str(Path(directory) /
                  f"guidance-%Y%m%dT%H%M%SZ-{session_token}.mp4")
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "image2pipe", "-framerate", str(fps), "-vcodec", "mjpeg",
        "-i", "pipe:0", "-an", "-c:v", "h264_v4l2m2m",
        "-b:v", str(bitrate), "-pix_fmt", "yuv420p", "-g", "30",
        "-f", "segment", "-segment_time", str(segment_seconds),
        "-reset_timestamps", "1", "-strftime", "1", pattern,
    ]
```

Generate `session_token` once with `secrets.token_hex(2)` so a rapid service restart cannot overwrite a same-second filename. Start FFmpeg with an environment copy containing `TZ=UTC`, `stdin=subprocess.PIPE`, and inherited stderr so encoder errors reach the journal without an unread stderr pipe. `prune_recordings()` considers only `guidance-*.mp4`, sorts by modification time then filename, excludes `active_path`, retains `keep_completed`, and catches no exceptions internally so the worker can report the exact retention failure.

- [ ] **Step 5: Implement the capacity-one recorder worker**

Use a `Condition` protecting `_pending_frame`, `_last_frame`, counters, and status. `publish()` only replaces `_pending_frame`, increments the drop counter when replacing an unconsumed frame, notifies the condition, and returns immediately. The worker writes at `1/fps`, repeats `_last_frame` when necessary, checks `process.poll()`, periodically prunes with the newest clip treated as active, and converts any exception into `RecorderStatus(state="failed", error=...)`.

`close()` sets the stop flag, joins the worker with the supplied timeout, closes stdin, waits for FFmpeg within the remaining timeout, then terminates it if needed. It performs final retention with no active path.

- [ ] **Step 6: Run recorder tests**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_guidance_recorder -v
```

Expected: all tests pass without an installed FFmpeg process because process creation is injected.

- [ ] **Step 7: Record the checkpoint**

Append verification to `work/verification-log.md`. If Git exists:

```bash
git add src/guidance_recorder.py tests/test_guidance_recorder.py work/verification-log.md
git commit -m "feat: add nonblocking rolling guidance recorder"
```

---

### Task 4: Runtime, Monitor, and Service Integration

**Files:**
- Modify: `src/autonomous_guidance.py`
- Modify: `src/guidance_web.py`
- Modify: `tests/test_autonomous_guidance.py`
- Modify: `tests/test_guidance_web.py`
- Modify: `deploy/rocket-guidance.service`
- Modify: `deploy/rocket-guidance.default`
- Modify: `scripts/install_guidance_service.sh`
- Modify: `tests/test_deployment_files.py`

**Interfaces:**
- Consumes: `RollingVideoRecorder`, `RecorderStatus`, structured overlay telemetry, and target FPS.
- Produces: recording fields in `FrameSnapshot.status()` and `/state`; automatic recorder lifecycle; systemd recording configuration.

- [ ] **Step 1: Write failing runtime isolation and cleanup tests**

```python
def test_runtime_publishes_annotated_jpeg_to_recorder():
    recorder = FakeRecorder()
    runtime = make_runtime(samples(0.0), [PAD], recorder=recorder)
    runtime.run_steps(1)
    self.assertEqual(recorder.frames, [(b"jpeg", 0.0)])

def test_recorder_failure_does_not_fault_guidance():
    recorder = FailedRecorder("disk full")
    runtime = make_runtime(samples(0.0, 0.1, 0.2), [PAD] * 3,
                           recorder=recorder)
    self.assertEqual(runtime.run_steps(3), 0)
    self.assertEqual(runtime.snapshot()["state"], "locked")
    self.assertEqual(runtime.snapshot()["recording"], "failed")
    self.assertEqual(runtime.snapshot()["recording_error"], "disk full")

def test_shutdown_neutralizes_before_closing_recorder():
    events = []
    runtime = runtime_with_shared_cleanup_events(events)
    runtime.run(stop_event=already_set_event())
    self.assertLess(events.index("servo-neutral"),
                    events.index("recorder-close"))
```

- [ ] **Step 2: Write failing state, page, and deployment tests**

```python
def test_state_includes_recording_metrics(self):
    state = get_json(server_for(runtime_with_recording()))
    self.assertEqual(state["recording"], "active")
    self.assertIn("recording_frames", state)
    self.assertIn("recording_dropped", state)
    self.assertIn("recording_error", state)

def test_service_enables_fifteen_fps_rolling_recording(self):
    defaults = DEFAULTS.read_text()
    self.assertIn("GUIDANCE_TARGET_FPS=15", defaults)
    self.assertIn("GUIDANCE_RECORDING=1", defaults)
    self.assertIn("GUIDANCE_RECORDING_SEGMENT_SECONDS=60", defaults)
    self.assertIn("GUIDANCE_RECORDING_KEEP_SEGMENTS=60", defaults)
    self.assertIn("GUIDANCE_RECORDING_BITRATE=2000000", defaults)
```

Also assert the installer creates `/home/pi/rocket/recordings` owned by `pi` and the service passes every recording environment variable as an explicit CLI argument.

- [ ] **Step 3: Run integration tests and verify RED**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_autonomous_guidance tests.test_guidance_web tests.test_deployment_files -v
```

Expected: missing recorder constructor/status fields and missing service configuration.

- [ ] **Step 4: Integrate recorder lifecycle and state**

Add optional `recorder=None` and `wall_clock=time.time` dependencies to `GuidanceRuntime`. After rendering, call `recorder.publish(jpeg, now)` and merge `recorder.status()` into `FrameSnapshot.status()`. Recorder exceptions are caught, logged, and translated into recording fields; they never call `guidance.fault()`.

In `main()`, parse:

```python
parser.add_argument("--target-fps", type=float, default=15.0)
parser.add_argument("--recording", type=int, choices=(0, 1), default=1)
parser.add_argument("--recording-dir", default="/home/pi/rocket/recordings")
parser.add_argument("--recording-fps", type=float, default=15.0)
parser.add_argument("--recording-bitrate", type=int, default=2_000_000)
parser.add_argument("--recording-segment-seconds", type=int, default=60)
parser.add_argument("--recording-keep-segments", type=int, default=60)
```

Create and start the recorder before entering `runtime.run()`. On shutdown, the runtime attempts servo neutral first, then closes the recorder, servo connection, and camera with bounded cleanup.

- [ ] **Step 5: Update monitor and service artifacts**

Show recording state, current clip, written frames, dropped frames, and errors on the monitor page. Add the exact defaults from the spec. Update `ExecStart` to pass target FPS and recording options. Update the installer:

```sh
RECORDING_DIR=/home/pi/rocket/recordings
install -d -o pi -g pi -m 0755 "$APP_DIR" "$LOG_DIR" "$RECORDING_DIR"
```

Preserve `GUIDANCE_MODE_ARG=--observe-only`.

- [ ] **Step 6: Run integration and complete local suites**

Run:

```powershell
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_autonomous_guidance tests.test_guidance_web tests.test_deployment_files -v
& 'C:\Users\remote.admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

Expected: zero failures and zero errors; previous lock, detection, neutral, and monitor tests remain green.

- [ ] **Step 7: Record the checkpoint**

Append verification to `work/verification-log.md`. If Git exists:

```bash
git add src/autonomous_guidance.py src/guidance_web.py tests/test_autonomous_guidance.py tests/test_guidance_web.py deploy scripts/install_guidance_service.sh tests/test_deployment_files.py work/verification-log.md
git commit -m "feat: integrate automatic guidance recording"
```

---

### Task 5: Pi Observe-Only Deployment and Performance Acceptance

**Files:**
- Modify: `outputs/autonomous-guidance-operations.md`
- Modify: `work/verification-log.md`
- Modify on Pi: `/home/pi/rocket`, `/etc/systemd/system/rocket-guidance.service`, `/etc/default/rocket-guidance`

**Interfaces:**
- Consumes: the exact locally tested sources and deployment artifacts from Tasks 1–4.
- Produces: an enabled observe-only Pi service sustaining 10–15 FPS with verified annotated rolling recordings.

- [ ] **Step 1: Build a clean deployment staging directory**

Create a new timestamped local directory containing only required `src/*.py`, `deploy/*`, and `scripts/install_guidance_service.sh`. Generate SHA-256 hashes and print the exact directory name:

```powershell
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$stage = Join-Path (Resolve-Path '.\work') "pi-guidance-deploy-$stamp"
New-Item -ItemType Directory -Path $stage | Out-Null
Write-Output $stage
```

Upload that directory under `/home/pi/` and verify remote hashes match the local manifest.

- [ ] **Step 2: Validate Pi prerequisites without stopping the working service**

Run on the Pi:

```sh
DEPLOY_DIR=$(find /home/pi -maxdepth 1 -type d -name 'pi-guidance-deploy-*' \
  -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)
ffmpeg -hide_banner -encoders | grep h264_v4l2m2m
bash -n "$DEPLOY_DIR/scripts/install_guidance_service.sh"
/home/pi/rocket/venv/bin/python -m py_compile "$DEPLOY_DIR"/src/*.py
df -h /home/pi
free -h
vcgencmd get_throttled
```

Expected: hardware encoder listed, syntax commands exit 0, at least 2 GB free, and throttling `0x0`.

- [ ] **Step 3: Preserve the working deployment and install without starting**

Create a uniquely named backup and record its exact path:

```sh
BACKUP_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="/home/pi/rocket-backups/before-high-fps-recording-$BACKUP_STAMP"
test ! -e "$BACKUP_DIR"
cp -a /home/pi/rocket "$BACKUP_DIR"
printf '%s\n' "$BACKUP_DIR"
```

Back up the current unit/default files in the same directory, run the installer with sudo, and verify defaults still contain `GUIDANCE_MODE_ARG=--observe-only` and `GUIDANCE_MAX_OFFSET=400`.

- [ ] **Step 4: Restart observe-only and verify neutral startup**

Run:

```sh
sudo systemctl restart rocket-guidance
systemctl is-active rocket-guidance
systemctl show rocket-guidance -p NRestarts -p MainPID --no-pager
curl -s http://127.0.0.1:8766/state
```

Expected: active, zero new restarts, `observe_only: true`, recording active, and actual outputs S7=1505, S8=1460, S9=1370, S10=1200.

- [ ] **Step 5: Run the 60-second pad-motion acceptance window**

Keep the service observe-only. Move the orange pad through center, all four cardinal directions, diagonals, and out of frame. Sample `/state` once per second for at least 60 seconds. Record minimum, median, and average guidance FPS, sequence growth, lock/loss transitions, recording drops, memory, CPU, and service restarts.

Expected: average FPS between 10 and 15, no sustained sample below 10 after warmup, lock after three compatible detections, loss neutral after 0.5 seconds, calibrated actual neutral throughout, and zero restarts.

- [ ] **Step 6: Verify the completed evidence clip**

After the first segment closes:

```sh
COMPLETED_FILE=$(find /home/pi/rocket/recordings -maxdepth 1 \
  -type f -name 'guidance-*.mp4' -printf '%T@ %p\n' \
  | sort -n | head -n1 | cut -d' ' -f2-)
test -n "$COMPLETED_FILE"
ffprobe -v error -show_entries stream=codec_name,width,height,avg_frame_rate \
  -show_entries format=duration -of json "$COMPLETED_FILE"
```

Expected: H.264, 640×480, approximately 15 FPS, approximately 60 seconds. Copy one completed clip to the workspace and visually inspect frames for rings, pad lock, state, requested direction, S7–S10 actual values and signed offsets, FPS, recording status, and timestamp.

- [ ] **Step 7: Verify rollover, retention logic, and failure visibility**

Confirm a second one-minute clip begins without stopping guidance. Run the retention function in a temporary directory populated with synthetic clip names; do not create 60 real minutes of video. Temporarily invoke a test recorder with an invalid output directory while the production service remains stopped, verify the error becomes visible and guidance tests remain green, then restore the production configuration.

- [ ] **Step 8: Record operation and recovery evidence**

Update `outputs/autonomous-guidance-operations.md` with the deployed paths, exact status/log/recording commands, observed FPS statistics, clip metadata, storage estimate, throttling value, rollback path, and the fact that live fin movement remains disabled.

Append every command and result to `work/verification-log.md`. If Git exists:

```bash
git add outputs/autonomous-guidance-operations.md work/verification-log.md
git commit -m "test: verify high-fps recorded guidance on pi"
```
