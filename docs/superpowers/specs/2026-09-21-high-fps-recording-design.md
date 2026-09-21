# High-FPS Guidance and Evidence Recording Design

**Date:** 2026-09-21

## Goal

Increase the autonomous camera-guidance loop from its measured 4.7 FPS to a sustained 10–15 FPS while automatically retaining one hour of annotated flight video. Recorded frames must provide enough evidence to compare visual guidance decisions with the commands sent to grid-fin servos S7–S10.

## Scope

This change covers:

- Pipelined MAVLink acknowledgement handling for each four-servo command cycle.
- A 15 FPS target for camera capture, pad detection, guidance, annotation, monitoring, and recording.
- Automatic annotated H.264 MP4 recording whenever the service runs.
- One-minute clips with rolling retention of the newest 60 completed clips.
- Recording status in runtime state and logs.
- Observe-only deployment and performance verification before any live fin activation.

Live fin activation remains governed by the existing restrained hardware procedure. Detection thresholds, guidance rings, three-frame acquisition, 0.5-second target-loss behavior, calibrated endpoints, and the ±400 microsecond maximum are unchanged.

## Current State

The Raspberry Pi Zero 2 W runs the IMX500 camera at 640×480. The current guidance service is stable in observe-only mode at about 4.7 FPS. Each control cycle sends four `MAV_CMD_DO_SET_SERVO` messages sequentially and waits for each acknowledgement before sending the next. The Pi has FFmpeg, the `h264_v4l2m2m` encoder, approximately 51 GB of free storage, and about 416 MiB of RAM.

## Runtime Architecture

### Camera and guidance loop

The main loop targets a 1/15-second interval. Each iteration:

1. Captures the newest 640×480 camera frame.
2. Runs orange-pad detection.
3. Updates the existing acquisition, lock, loss, and fault state machine.
4. Calculates four bounded output commands.
5. Sends and verifies one four-output MAVLink batch.
6. Produces one annotated frame shared by the browser monitor and recorder.
7. Publishes current guidance and recording state.

The measured FPS continues to describe completed guidance frames rather than browser refreshes or duplicated recording frames.

### Pipelined servo command batch

`MavlinkServoController.send_cycle()` will retain its existing validation and fail-neutral behavior. It will send all four validated `MAV_CMD_DO_SET_SERVO` messages first, then wait for four accepted `COMMAND_ACK` messages within one bounded cycle deadline.

No other component may write servo commands through that MAVLink connection. Because `COMMAND_ACK` does not identify the servo channel, successful verification means four accepted acknowledgements for the four-command batch. A rejection, missing acknowledgement, stale heartbeat, parameter mismatch, or serial exception faults the runtime and attempts immediate neutral.

### Annotated evidence frame

The annotation stage creates one frame containing:

- The 5%, 25%, 50%, and 75% guidance rings.
- Camera center marker.
- Detected landing-pad bounding box and center marker.
- A line from camera center to target center.
- Guidance state and acquisition count.
- Requested correction magnitude and direction.
- S7–S10 command values.
- Signed S7–S10 offsets from their calibrated neutral values.
- Observe-only or live status.
- Measured guidance FPS.
- Recording state.
- Wall-clock timestamp suitable for matching the video with logs.

In observe-only mode, the frame shows both the calculated guidance request and the actual neutral values sent to the controller. In live mode, it shows the actual bounded values sent.

## Recording Pipeline

### Isolation from guidance

Recording runs in a dedicated worker and FFmpeg subprocess. The guidance loop publishes the latest annotated JPEG to a capacity-one handoff. Publishing never waits for disk or FFmpeg. When the recorder is behind, a newer frame replaces the pending older frame and increments a dropped-frame counter.

The recorder writes at a nominal 15 FPS. It may repeat the latest annotated frame when no newer frame arrives by the next recording interval. This keeps clip duration aligned with wall-clock time without delaying guidance.

### Encoding and files

FFmpeg consumes the annotated JPEG stream and uses the Pi's `h264_v4l2m2m` H.264 encoder. Initial settings are:

- Resolution: 640×480.
- Nominal frame rate: 15 FPS.
- Video bitrate: 2 Mbit/s.
- No audio.
- Container: MP4.
- Segment duration: one minute.
- Directory: `/home/pi/rocket/recordings`.
- Filename: UTC start time, for example `guidance-20260921T041500Z.mp4`.

At 2 Mbit/s, one hour is approximately 900 MB before container overhead, which fits comfortably within the currently available storage.

### Retention

The newest 60 completed one-minute clips are retained. The active clip is never deleted. After a clip closes, the recorder deletes older completed clips until 60 remain. Unrelated files in the recording directory are ignored.

On clean shutdown, the service closes FFmpeg input and allows the active MP4 to finalize. If power is removed abruptly, the active one-minute clip may be damaged; previously completed clips remain intact.

## Failure Behavior

Guidance safety has priority over recording.

- If FFmpeg cannot start, exits, blocks, or rejects input, guidance continues and the runtime reports recording as failed.
- A recorder failure is logged immediately and exposed through `/state` with its reason.
- The recorder never commands servos and never owns the camera.
- A full disk or retention error does not block camera guidance.
- Camera, MAVLink, parameter, command, shutdown, and internal guidance faults retain the existing neutral behavior.
- Service shutdown stops guidance, attempts servo neutral, closes the camera, closes the recorder input, and waits a bounded time for FFmpeg to finalize.

The service may attempt a bounded recorder restart after failure. Repeated failures remain visible and do not restart the complete guidance service.

## Runtime Configuration

The systemd environment file gains:

```ini
GUIDANCE_TARGET_FPS=15
GUIDANCE_RECORDING=1
GUIDANCE_RECORDING_DIR=/home/pi/rocket/recordings
GUIDANCE_RECORDING_FPS=15
GUIDANCE_RECORDING_BITRATE=2000000
GUIDANCE_RECORDING_SEGMENT_SECONDS=60
GUIDANCE_RECORDING_KEEP_SEGMENTS=60
```

The service creates the recording directory owned by user `pi`. Recording is automatic at service startup and does not depend on Wi-Fi or a browser.

## Monitor and Logs

The `/state` response and monitor page add:

- `recording`: active, starting, failed, or stopped.
- Current clip path.
- Recorder frames written.
- Recorder frames dropped.
- Recorder error text.

State-transition logs remain immediate. Once-per-second status logs add measured guidance FPS, recording state, and dropped-frame count. Video frames show the same servo values published in `/state` for that guidance result.

## Testing

Implementation follows test-driven development.

### Servo tests

- Each servo command receives its acknowledgement before the next identical
  MAVLink command type is sent.
- A dedicated latest-value worker keeps acknowledged serial traffic off the
  camera processing thread.
- New guidance replaces a stale command waiting in the worker queue.
- Unchanged fin positions are not resent, changed positions are capped at 8 Hz,
  and a timed-out MAVLink command is retried up to three times.
- Missing, rejected, or unrelated acknowledgements fail the cycle.
- Invalid commands are rejected before any serial write.
- Fault and shutdown paths still attempt calibrated neutral.

Hardware profiling on 2026-09-21 showed why the worker is required: the
camera/detection/overlay/JPEG path sustained 11.75 FPS by itself, while one
safe sequential four-servo cycle averaged 88 ms. Pipelining four
`MAV_CMD_DO_SET_SERVO` messages made the acknowledgements ambiguous and caused
a real 2-of-4 acknowledgement fault. The worker preserves sequential command
acknowledgements while allowing the camera and recorder to proceed in parallel.
Subsequent hardware runs also measured healthy one-Hz heartbeat jitter slightly
above one second and one dropped acknowledgement after 58 seconds. The final
transport therefore uses a 2.5-second heartbeat threshold, incremental setting
validation, command retries, changed-value suppression, and an 8 Hz maximum
servo update rate.

### Recorder tests

- Published frames do not block when the recorder is slow.
- A newer frame replaces an older pending frame and increments the drop count.
- FFmpeg receives annotated frames rather than raw camera frames.
- Retention keeps 60 completed clips, preserves the active clip, and ignores unrelated files.
- FFmpeg failure is reported without stopping the guidance loop.
- Clean shutdown closes and waits for the encoder with a timeout.

### Runtime and overlay tests

- The annotation contains state, target, requested direction, actual S7–S10 values, signed neutral offsets, FPS, recording state, and timestamp.
- Observe-only video shows calculated correction with actual neutral commands.
- Existing lock, hysteresis, loss, fault, monitor, and servo-limit tests remain green.

## Deployment and Acceptance

1. Run the complete local test suite.
2. Upload the exact tested files to a new Pi staging directory.
3. Preserve the currently working deployment and configuration as a timestamped backup.
4. Validate Python, shell, systemd, and FFmpeg configuration without starting live control.
5. Restart in observe-only mode.
6. Run for at least 60 seconds with recording active and the pad moving through multiple zones.
7. Confirm guidance averages 10–15 FPS, frame sequence advances, neutral values remain S7=1505, S8=1460, S9=1370, and S10=1200, and the service does not restart.
8. Verify the completed MP4 with `ffprobe`, inspect its duration, frame rate, resolution, codec, and burned-in overlays.
9. Verify a second segment begins and retention logic does not touch unrelated files.
10. Inspect memory, CPU load, storage growth, logs, and `vcgencmd get_throttled`.

If observe-only performance is below 10 FPS, recording remains disabled in the boot configuration while profiling continues. Live servo control is not enabled as part of this performance and recording rollout.

## Success Criteria

- Sustained measured guidance rate of 10–15 FPS on the Pi with recording active.
- Stable observe-only service with zero unexpected restarts.
- Playable one-minute H.264 MP4 clips with all required guidance and servo overlays.
- Automatic one-hour rolling retention.
- Recording latency or failure cannot delay the guidance loop.
- Existing neutral, limit, loss, and fault guarantees remain verified.
