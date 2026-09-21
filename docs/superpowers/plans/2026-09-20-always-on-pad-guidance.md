# Always-On Landing-Pad Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run orange-pad detection and bounded grid-fin guidance automatically whenever the Raspberry Pi is powered, without depending on Wi-Fi or a browser.

**Architecture:** A systemd-managed Python process owns the camera and MAVLink connection. A pure state machine converts temporally consistent detections into four bounded servo commands, while a separate monitor serves the latest already-processed frame and status without driving the control loop.

**Tech Stack:** Python 3, `unittest`, Picamera2, Pillow, NumPy, pymavlink, systemd, logrotate

**Spec:** `docs/superpowers/specs/2026-09-20-always-on-pad-guidance-design.md`

## Global Constraints

- Camera: Raspberry Pi AI Camera at 640 × 480 with BGR array interpretation.
- Flight-controller link: `/dev/serial0` at 57600 baud.
- Outputs: S7–S10 only; `SERVOx_FUNCTION` must remain 0.
- Calibration: S7 1105/1505/1905, S8 1060/1460/1860, S9 970/1370/1770, S10 800/1200/1600.
- Final correction cap: ±400 µs, scaled uniformly when any individual output would cross its saved limit.
- Lock: three compatible consecutive detections.
- Loss timeout: 0.5 seconds, followed by neutral.
- Camera guidance starts from target acquisition alone; it has no launch, altitude, descent, parachute, network, or browser gate.
- Any camera, MAVLink, parameter, command, shutdown, or internal fault commands neutral whenever communication permits.
- The operator `Stop and neutral` action latches guidance off until service restart.
- Motor and ignition circuits remain disconnected for every bench step in this plan.

## Review Focus

- An orange object appearing for only one or two frames must never leave neutral; Task 1 tests acquisition reset.
- A target oscillating around 25%, 50%, or 75% radius must not chatter between adjacent zones; Task 1 tests hysteresis in both directions.
- A diagonal ±400 µs request must preserve direction while scaling all four outputs into unequal saved limits; Task 2 tests uniform scale.
- A camera freeze that leaves the last target visible in memory must become neutral after 0.5 seconds; Task 3 tests stale-frame handling.
- Browser disconnection or multiple browser clients must not pause, accelerate, or duplicate servo commands; Task 4 tests monitor-only behavior.

---

### Task 1: Pure Guidance State Machine

**Files:**
- Create: `src/guidance_state.py`
- Create: `tests/test_guidance_state.py`
- Modify: `src/camera_zones.py`
- Test: `tests/test_camera_zones.py`

**Interfaces:**
- Consumes: `camera_zones.decide(target_center, frame_size, max_tested_us=400)` and `bench_ball_sim.bounded_pulses_for(decision, settings)`.
- Produces: `GuidanceController.update(observation: Observation | None, now: float) -> GuidanceOutput`, `GuidanceController.inhibit() -> GuidanceOutput`, and immutable `Observation`/`GuidanceOutput` records.

- [x] **Step 1: Write failing acquisition and loss tests**

```python
def test_three_compatible_frames_establish_lock():
    controller = GuidanceController(expected_settings(), max_offset=400)
    assert controller.update(obs((200, 240), 0.0), 0.0).state == State.ACQUIRING
    assert controller.update(obs((202, 239), 0.1), 0.1).state == State.ACQUIRING
    output = controller.update(obs((201, 241), 0.2), 0.2)
    assert output.state == State.LOCKED
    assert output.pulses != NEUTRAL

def test_one_frame_flash_returns_to_search_without_movement():
    controller = GuidanceController(expected_settings(), max_offset=400)
    controller.update(obs((200, 240), 0.0), 0.0)
    output = controller.update(None, 0.1)
    assert output.state == State.SEARCHING
    assert output.pulses == NEUTRAL

def test_locked_target_loss_becomes_neutral_after_half_second():
    controller = locked_controller()
    held = controller.update(None, 1.3)
    neutral = controller.update(None, 1.51)
    assert held.state == State.LOST
    assert neutral.state == State.SEARCHING
    assert neutral.pulses == NEUTRAL
```

- [x] **Step 2: Run the new test file and verify RED**

Run: `python -m unittest tests.test_guidance_state -v`

Expected: import failure for `guidance_state`.

- [x] **Step 3: Implement the state records and acquisition compatibility**

Create:

```python
class State(Enum):
    STARTING = "starting"
    SEARCHING = "searching"
    ACQUIRING = "acquiring"
    LOCKED = "locked"
    LOST = "lost"
    FAULT = "fault"
    INHIBITED = "inhibited"

@dataclass(frozen=True)
class Observation:
    center: tuple[int, int]
    frame_size: tuple[int, int]
    area_fraction: float
    captured_at: float

@dataclass(frozen=True)
class GuidanceOutput:
    state: State
    pulses: dict[int, int]
    requested_us: int
    target: tuple[int, int] | None
    reason: str
```

Compatibility requires equal frame size, center movement no greater than 12% of the shorter image dimension, and area ratio between 0.5 and 2.0.

- [x] **Step 4: Implement lock, lost, inhibited, and fault transitions**

`SEARCHING` and `ACQUIRING` always output `NEUTRAL`. The third compatible observation enters `LOCKED`. Missing observations while locked enter `LOST` and hold the last command without increasing it for at most 0.5 seconds; expiration returns neutral and `SEARCHING`. `inhibit()` latches `INHIBITED` and neutral. `fault(reason)` latches `FAULT` and neutral.

- [x] **Step 5: Write failing zone-hysteresis tests**

```python
def test_locked_zone_holds_near_25_percent_boundary():
    controller = locked_controller_at_radius(0.24)
    assert controller.update(obs_at_radius(0.255, 1.0), 1.0).requested_us == 100
    assert controller.update(obs_at_radius(0.29, 1.1), 1.1).requested_us == 200

def test_hysteresis_allows_correction_to_decrease_after_crossing_margin():
    controller = locked_controller_at_radius(0.55)
    assert controller.update(obs_at_radius(0.49, 1.0), 1.0).requested_us == 300
    assert controller.update(obs_at_radius(0.46, 1.1), 1.1).requested_us == 200
```

- [x] **Step 6: Implement 3%-radius hysteresis around the 25%, 50%, and 75% boundaries**

Add `decide_with_hysteresis(target_center, frame_size, previous_requested_us, margin=0.03, max_tested_us=400)` to `camera_zones.py`. The 5% dead zone has priority and immediately requests zero.

- [x] **Step 7: Run Task 1 and existing camera-zone tests**

Run: `python -m unittest tests.test_guidance_state tests.test_camera_zones -v`

Expected: all tests pass.

- [x] **Step 8: Record the checkpoint**

This workspace currently has no Git repository. Record the passing command and output in `work/verification-log.md`. If the user initializes Git before execution, commit with message `feat: add autonomous guidance state machine`.

---

### Task 2: Reusable Fail-Neutral MAVLink Servo Controller

**Files:**
- Create: `src/servo_controller.py`
- Create: `tests/test_servo_controller.py`
- Modify: `src/bench_ball_sim.py`
- Modify: `tests/test_bench_ball_sim.py`

**Interfaces:**
- Consumes: pymavlink connection object and four-channel pulse dictionaries.
- Produces: `MavlinkServoController.connect()`, `send_cycle(pulses, now)`, `neutral()`, `check_health(now)`, and `close()`.

- [x] **Step 1: Write failing tests with a deterministic fake MAVLink connection**

Cover exact startup parameter reads, armed/disarmed heartbeat parsing without using it as a guidance gate, four commands per control cycle, rejected acknowledgement, heartbeat older than 1.0 second, periodic parameter mismatch, and neutral-before-close.

```python
def test_diagonal_request_scales_all_axes_to_saved_limits():
    decision = decide((0, 0), (640, 480), max_tested_us=400)
    pulses = bounded_pulses_for(decision, expected_settings())
    assert all(expected_settings()[ch]["min"] <= pwm <= expected_settings()[ch]["max"]
               for ch, pwm in pulses.items())
    x_scale = (pulses[8] - NEUTRAL[8]) / (pulses_for(decision)[8] - NEUTRAL[8])
    y_scale = (pulses[7] - NEUTRAL[7]) / (pulses_for(decision)[7] - NEUTRAL[7])
    assert abs(x_scale - y_scale) < 0.01

def test_close_attempts_neutral_before_serial_close():
    controller = connected_fake_controller()
    controller.close()
    assert controller.connection.events[-2:] == [("cycle", NEUTRAL), ("close",)]
```

- [x] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_servo_controller -v`

Expected: import failure for `servo_controller`.

- [x] **Step 3: Extract calibration and validation from `bench_ball_sim.py`**

Move `NEUTRAL`, expected settings, command validation, and MAVLink connection behavior into `servo_controller.py`. Keep compatibility imports in `bench_ball_sim.py` so existing simulation tests continue to pass.

- [x] **Step 4: Implement health and neutral guarantees**

`connect()` waits up to eight seconds for a heartbeat and validates all 16 servo parameters. `send_cycle()` validates all four commands before sending any command and confirms each `MAV_CMD_DO_SET_SERVO` acknowledgement. `check_health()` fails when heartbeat age exceeds 1.0 second and re-reads servo parameters every ten seconds. `close()` attempts neutral in a `try/finally` before closing serial.

- [x] **Step 5: Run controller and simulation tests**

Run: `python -m unittest tests.test_servo_controller tests.test_bench_ball_sim tests.test_live_bench_sim -v`

Expected: all tests pass.

- [x] **Step 6: Record the checkpoint**

Append the passing command to `work/verification-log.md`; if Git exists, commit with message `refactor: add fail-neutral servo controller`.

---

### Task 3: Camera-Owned Autonomous Control Loop

**Files:**
- Create: `src/autonomous_guidance.py`
- Create: `tests/test_autonomous_guidance.py`
- Modify: `src/orange_pad.py`

**Interfaces:**
- Consumes: `GuidanceController`, `MavlinkServoController`, Picamera2 frames, and `detect_orange_pad`.
- Produces: `GuidanceRuntime.run(stop_event)`, `GuidanceRuntime.stop_and_neutral()`, `GuidanceRuntime.snapshot()`, and `FrameSnapshot` containing the latest raw frame, detection, annotated JPEG, status, and timestamp.

- [x] **Step 1: Write failing control-loop tests**

Use fake camera, detector, clock, and servo controller. Test that the loop runs without a browser client, sends neutral while searching/acquiring, begins motion on the third compatible detection, sends the ±400-zone output, detects a stale frozen frame, and always neutralizes in `finally`.

```python
def test_browser_is_not_required_for_camera_and_servo_updates():
    runtime = runtime_with_frames([pad_frame()] * 4)
    runtime.run_steps(4)
    assert runtime.frame_hub.sequence == 4
    assert runtime.servo.cycles[-1] != NEUTRAL

def test_frozen_camera_timestamp_faults_and_neutralizes():
    runtime = runtime_with_repeated_timestamp(pad_frame(), timestamp=1.0)
    runtime.run_steps(8, clock_values=[1.0, 1.1, 1.2, 1.7])
    assert runtime.snapshot()["state"] == "fault"
    assert runtime.servo.cycles[-1] == NEUTRAL
```

- [x] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_autonomous_guidance -v`

Expected: import failure for `autonomous_guidance`.

- [x] **Step 3: Implement `FrameHub` and the deterministic loop**

The camera loop captures independently at its natural rate. Each loop iteration detects the pad with `sample_step=8`, creates an `Observation`, updates `GuidanceController`, checks MAVLink health, sends one four-output control cycle, draws the annotation once, and atomically publishes the latest status/JPEG to `FrameHub`.

- [x] **Step 4: Implement fault and shutdown cleanup**

Wrap runtime operation in `try/except/finally`. Exceptions set `FAULT`, publish the reason, command neutral, close the servo link, stop/close the camera, and return a nonzero process exit so systemd can restart it. SIGINT and SIGTERM set the stop event and follow the same neutral cleanup.

- [x] **Step 5: Add rotating application logging**

Use `logging.handlers.RotatingFileHandler('/home/pi/rocket/logs/guidance.log', maxBytes=2_000_000, backupCount=4)` plus stderr. Log state transitions immediately and target/PWM samples no faster than once per second.

- [x] **Step 6: Run Task 3 plus detector tests**

Run: `python -m unittest tests.test_autonomous_guidance tests.test_orange_pad tests.test_guidance_state -v`

Expected: all tests pass.

- [x] **Step 7: Record the checkpoint**

Append verification to `work/verification-log.md`; if Git exists, commit with message `feat: add autonomous camera guidance runtime`.

---

### Task 4: Monitor-Only Browser Interface

**Files:**
- Create: `src/guidance_web.py`
- Create: `tests/test_guidance_web.py`
- Modify: `src/autonomous_guidance.py`
- Modify: `src/live_camera_bench.py`
- Modify: `tests/test_live_camera_bench.py`

**Interfaces:**
- Consumes: `FrameHub.latest()` and `GuidanceRuntime.stop_and_neutral()`.
- Produces: `make_monitor_server(runtime, host='127.0.0.1', port=8766)` with `/`, `/stream.mjpg`, `/state`, and `/stop`.

- [x] **Step 1: Write failing monitor-isolation tests**

```python
def test_two_stream_clients_do_not_capture_or_command_hardware():
    runtime = FakeRuntime()
    server = make_monitor_server(runtime)
    read_one_stream_part(server)
    read_one_stream_part(server)
    assert runtime.camera_calls == 0
    assert runtime.servo_calls == 0

def test_stop_latches_inhibit_and_neutral():
    runtime = FakeRuntime()
    response = post(server_for(runtime), "/stop")
    assert response.status == 200
    assert runtime.stop_and_neutral_calls == 1
    assert runtime.snapshot()["state"] == "inhibited"
```

- [x] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_guidance_web -v`

Expected: import failure for `guidance_web`.

- [x] **Step 3: Move reusable MJPEG and page behavior into `guidance_web.py`**

The stream repeatedly publishes the newest already-rendered JPEG from `FrameHub`; it never calls `camera.capture_array()`, target detection, or servo methods. `/state` returns sequence, state, target, zone, FPS, heartbeat age, fault reason, and S7–S10 PWM values. `/stop` calls the runtime inhibit method once.

- [x] **Step 4: Change the page from timed bench controls to autonomous status**

Show `SEARCHING`, `ACQUIRING 1/3`, `LOCKED`, `LOST`, `FAULT`, or `INHIBITED`; display the current ring and output values. Remove `Start fin test`. Keep a clearly labeled `Stop and neutral` button whose response explains that restart is required to re-enable guidance.

- [x] **Step 5: Start the monitor as a non-owning runtime thread**

Update `autonomous_guidance.main()` to create one `GuidanceRuntime`, start `make_monitor_server(runtime)` in a daemon thread, and run the camera/control loop on the main thread. Server shutdown occurs in the same `finally` cleanup, while a server exception records status without terminating the guidance loop.

- [x] **Step 6: Keep `live_camera_bench.py` as a separate manual test utility**

Update its imports to reuse MJPEG helpers without starting the autonomous runtime. This preserves the existing finite bench tool for diagnostics while ensuring the systemd service runs only `autonomous_guidance.py`.

- [x] **Step 7: Run browser, runtime, and previous preview tests**

Run: `python -m unittest tests.test_guidance_web tests.test_live_camera_bench tests.test_camera_zone_preview tests.test_autonomous_guidance -v`

Expected: all tests pass and no test requires camera hardware.

- [x] **Step 8: Record the checkpoint**

Append verification to `work/verification-log.md`; if Git exists, commit with message `feat: add autonomous guidance monitor`.

---

### Task 5: Boot Service and Installation Artifacts

**Files:**
- Create: `deploy/rocket-guidance.service`
- Create: `deploy/rocket-guidance.default`
- Create: `deploy/rocket-guidance.logrotate`
- Create: `scripts/install_guidance_service.sh`
- Create: `tests/test_deployment_files.py`

**Interfaces:**
- Consumes: `/home/pi/rocket/venv/bin/python`, `/home/pi/rocket/autonomous_guidance.py`, `/dev/serial0`, and camera access available to user `pi`.
- Produces: an enabled `rocket-guidance.service` with `GUIDANCE_MAX_OFFSET=400`, localhost port 8766, restart-on-failure, and neutral cleanup on stop.

- [x] **Step 1: Write failing deployment-file tests**

Assert that the unit contains `User=pi`, `WorkingDirectory=/home/pi/rocket`, `EnvironmentFile=-/etc/default/rocket-guidance`, `Restart=on-failure`, `RestartSec=2`, `TimeoutStopSec=8`, and no `network-online.target` dependency. Assert that defaults set `GUIDANCE_MAX_OFFSET=400` and `GUIDANCE_MODE_ARG=--observe-only` for initial installation. Assert that the installer performs `systemctl daemon-reload` and enables but does not start the service automatically.

- [x] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_deployment_files -v`

Expected: missing deployment files.

- [x] **Step 3: Write the unit and defaults**

Use:

```ini
[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/rocket
EnvironmentFile=-/etc/default/rocket-guidance
ExecStart=/home/pi/rocket/venv/bin/python /home/pi/rocket/autonomous_guidance.py --port /dev/serial0 --baud 57600 --http-port 8766 --max-offset ${GUIDANCE_MAX_OFFSET} ${GUIDANCE_MODE_ARG}
Restart=on-failure
RestartSec=2
TimeoutStopSec=8
KillSignal=SIGINT
```

Set `GUIDANCE_MAX_OFFSET=400` and `GUIDANCE_MODE_ARG=--observe-only` initially. Observe-only performs detection, state transitions, and monitoring but forces neutral. The final hardware task removes `--observe-only` only after the staged bench checks pass.

- [x] **Step 4: Write an idempotent installer**

The script copies source files to `/home/pi/rocket`, installs the unit/default/logrotate files with root ownership, creates `/home/pi/rocket/logs` owned by `pi`, reloads systemd, and enables the unit. It must not start or restart a running service.

- [ ] **Step 5: Run deployment tests and shell syntax check**

Run: `python -m unittest tests.test_deployment_files -v`

Run on Pi before installation: `bash -n /home/pi/rocket/install_guidance_service.sh`

Expected: all tests pass and shell syntax exits 0.

- [ ] **Step 6: Record the checkpoint**

Append verification to `work/verification-log.md`; if Git exists, commit with message `feat: add guidance boot service`.

---

### Task 6: Full Local Verification and Pi Observe-Only Deployment

**Files:**
- Modify: `outputs/pi-camera-setup.md`
- Create: `outputs/autonomous-guidance-operations.md`
- Modify: `work/verification-log.md`

**Interfaces:**
- Consumes: all source, tests, and deployment artifacts from Tasks 1–5.
- Produces: an enabled observe-only Pi service and a verified boot/search/lock monitor without autonomous servo movement.

- [ ] **Step 1: Run the complete local suite**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 2: Deploy files without starting the service**

Copy the exact tested files to `/home/pi/rocket`, run `bash -n`, then run the installer. Preserve the existing files as a timestamped backup before replacing them.

- [ ] **Step 3: Stop the old preview and manual bench processes**

Identify exact PIDs and command lines, command neutral through the existing interface, stop only those identified processes, and verify port 8766 and `/dev/serial0` have no competing owner.

- [ ] **Step 4: Start observe-only mode and inspect status**

Run: `sudo systemctl start rocket-guidance`; then inspect `systemctl status`, `journalctl -u rocket-guidance`, the local `/state` response, and the latest rotating log. Expected state is `SEARCHING` or `ACQUIRING/LOCKED`, all four reported PWM values equal calibrated neutral, and no network dependency.

- [ ] **Step 5: Verify autonomous operation without the browser**

Close the browser and SSH session for at least 30 seconds, reconnect, and confirm frame sequence, detector state, and log timestamps advanced while no client was connected.

- [ ] **Step 6: Verify boot without Wi-Fi**

With the service still observe-only, disable the hotspot, power-cycle the Pi, wait for local boot, restore the hotspot, and confirm logs show the service started and processed frames before networking returned.

- [ ] **Step 7: Document operation and recovery**

Write exact commands for status, logs, stop, restart, observe-only mode, live mode, and emergency neutral. Record the observed boot time, FPS, and state transitions in `outputs/autonomous-guidance-operations.md`.

---

### Task 7: Restrained Hardware Activation and Final Autostart

**Files:**
- Modify on Pi: `/etc/default/rocket-guidance`
- Modify: `outputs/autonomous-guidance-operations.md`
- Modify: `work/verification-log.md`

**Interfaces:**
- Consumes: the observe-only service proven in Task 6.
- Produces: autonomous guidance enabled at boot with the final ±400 µs cap, plus recorded bench evidence for every required neutral and fault path.

- [ ] **Step 1: Establish the physical test condition**

Immediately before servo activation, verify with the user that the rocket is restrained, hands are clear, the motor and ignition circuits are disconnected, the flight controller is disarmed, and the pad is controllably movable through the camera image.

- [ ] **Step 2: Activate a temporary ±200 µs live cap**

Set `GUIDANCE_MAX_OFFSET=200` and remove `--observe-only`, restart the service, and verify S7–S10 parameters before moving the pad into view. Exercise left, right, up, down, diagonal, center, and target-loss cases. Confirm all fins remain smooth, clear, and quiet.

- [ ] **Step 3: Test emergency inhibit and restart behavior**

While locked at ±200 µs, use `Stop and neutral`. Verify all four reported outputs and physical fins return to neutral, the state remains `INHIBITED`, and moving the pad does not re-enable commands. Restart the service and verify searching resumes from neutral.

- [ ] **Step 4: Test camera and MAVLink faults at ±200 µs**

Induce each fault separately using reversible disconnections. Verify target loss or stale camera returns neutral within 0.5 seconds, serial loss records `FAULT`, and all outputs that remain reachable are neutral. Restore each connection and restart cleanly.

- [ ] **Step 5: Activate the final ±400 µs cap**

Set `GUIDANCE_MAX_OFFSET=400`, restart, and move the pad progressively through the 100, 200, 300, and 400 µs rings. Verify physical clearance, no buzzing or binding, correct paired direction, per-servo limits, centered neutral, and lost-target neutral.

- [ ] **Step 6: Power-cycle and verify final autonomous startup**

With the pad initially absent, power-cycle the complete electronics. Confirm neutral during startup/search, three-frame lock when the pad appears, full ring behavior, and neutral after removal. Repeat once without an active browser client.

- [ ] **Step 7: Run final software and live-status verification**

Run locally: `python -m unittest discover -s tests -v`.

Run on Pi: `systemctl is-enabled rocket-guidance`, `systemctl is-active rocket-guidance`, inspect `/state`, and verify `vcgencmd get_throttled` returns `0x0`.

Expected: all tests pass; service enabled and active; state matches the visible target; no undervoltage/throttling flags; final centered or no-target output equals S7=1505, S8=1460, S9=1370, S10=1200.

- [ ] **Step 8: Record the final evidence**

Append commands, timestamps, test observations, and final parameters to `work/verification-log.md` and `outputs/autonomous-guidance-operations.md`. If Git exists, commit with message `feat: enable always-on landing-pad guidance`.
