# Always-On Landing-Pad Guidance Design

Date: 2026-09-20

## Purpose

Make the Raspberry Pi Zero 2 W search for the orange 4 ft × 4 ft landing pad whenever the rocket is powered. When the camera establishes a reliable pad lock, the Pi immediately commands the four grid-fin servos through the Matek H743-SLIM V4 to move the pad toward the center of the image.

The system must operate without a laptop, hotspot, browser, altitude trigger, descent trigger, parachute trigger, or manual start action. The browser remains an optional monitor and emergency neutral control.

## Existing Hardware and Calibration

- Raspberry Pi Zero 2 W with Raspberry Pi AI Camera (IMX500)
- Matek H743-SLIM V4 running ArduPlane
- Four SG90 servos on outputs S7 through S10
- Pi-to-flight-controller MAVLink connection on `/dev/serial0` at 57600 baud
- Camera frames at 640 × 480 with the working BGR channel interpretation
- Individual servo settings:

| Output | Position | Minimum | Neutral | Maximum |
| --- | --- | ---: | ---: | ---: |
| S7 | Right of camera | 1105 | 1505 | 1905 |
| S8 | Above camera | 1060 | 1460 | 1860 |
| S9 | Below camera | 970 | 1370 | 1770 |
| S10 | Left of camera | 800 | 1200 | 1600 |

The intended camera-space steering map is:

- Image left/right: S8 and S9 move with opposite PWM signs.
- Image up/down: S7 and S10 move with opposite PWM signs.
- Diagonal errors combine both pairs.

These directions have been verified mechanically on the bench. Their aerodynamic response has not been verified in flight.

## Architecture

The Pi runs one systemd-managed guidance service. The service owns the camera and MAVLink connection, performs detection, maintains the guidance state, sends servo commands, records status, and provides the optional localhost browser interface.

The service starts automatically at boot after the required device nodes become available. It does not depend on networking. systemd restarts it after an unexpected exit.

Only one process may own guidance output. The previous timed bench process must not run alongside the autonomous service.

## Guidance States

### STARTING

1. Open the camera.
2. Open `/dev/serial0` and receive a flight-controller heartbeat.
3. Read `SERVO7` through `SERVO10` function, minimum, maximum, and trim parameters.
4. Compare the parameters with the saved calibration above.
5. Command all four calibrated neutral values.

If initialization fails, enter `FAULT` without enabling guidance.

### SEARCHING

- Process camera frames continuously.
- Keep all fins at their calibrated neutral positions.
- Track plausible orange rectangular candidates.
- Begin acquisition when a candidate is detected.

### ACQUIRING

- Require three consecutive detections with compatible center and apparent size.
- Reset acquisition when a detection is missing or moves by an implausible amount between frames.
- At the current 7–10 fps, acquisition normally takes about 0.3–0.5 seconds.
- Enter `LOCKED` after the third accepted detection.

### LOCKED

- Calculate the pad center relative to the camera center.
- Select correction magnitude from the existing concentric zones:

| Radius from image center | Requested correction |
| --- | ---: |
| 0–5% | 0 µs |
| Over 5% through 25% | 100 µs |
| Over 25% through 50% | 200 µs |
| Over 50% through 75% | 300 µs |
| Over 75% | 400 µs |

- Project the selected correction onto the horizontal and vertical error direction.
- Convert the two axes into S7–S10 PWM commands using the established paired-fin signs.
- Scale both axes together when necessary so no servo crosses its saved individual minimum or maximum.
- Apply small zone-boundary hysteresis so measurement noise does not repeatedly switch between neighboring correction levels.
- Continue guidance at approximately 10 commands per second.
- If the pad is centered within the 5% dead zone, command neutral while retaining lock.

### LOST

- A missing detection starts a 0.5-second loss timer.
- During the brief gap, do not increase the previous correction.
- If no valid target returns before the timer expires, command neutral and enter `SEARCHING`.
- If a compatible target returns before expiration, resume `LOCKED` control.

### FAULT

Command neutral whenever possible, stop guidance output, record the fault, and wait for systemd restart or operator action. Fault causes include:

- Camera failure or stale frames
- Lost MAVLink heartbeat
- Servo command rejection or missing acknowledgement
- Servo parameters differing from the approved calibration
- Internal exception
- Service shutdown or restart

### INHIBITED

The browser's `Stop and neutral` control latches the service in an inhibited state. Detection and monitoring may continue, but every servo stays at its calibrated neutral. Guidance remains inhibited until the service is deliberately restarted, preventing an accidental or stale browser request from re-enabling fin movement.

## Target Detection

The detector uses the tested orange HSV thresholds, rectangular shape checks, minimum area, and morphological closing needed to join the visible orange regions separated by the pad's black crossed straps.

The production detector keeps the current sampling resolution that tracks the pad center within a few pixels while supporting the faster preview. Acquisition adds temporal consistency so a single orange flash cannot establish lock.

The detector searches from boot onward. There is deliberately no flight-phase gate. Therefore, a powered rocket that can see the pad on the ground will move its fins toward the detected pad.

## Servo Command Rules

- Maximum requested offset is the full bench-tested ±400 µs.
- Commands always remain within the saved per-servo limits.
- The four calibrated neutral values are used; a universal 1500 µs neutral is not allowed.
- All four servo commands are calculated from the same camera sample and sent within one control cycle.
- Servo settings are checked at startup and periodically while running.
- Loss of target, stale input, stopped service, or detected fault returns all outputs to neutral.
- The service does not command the parachute, motor, ignition system, or any output outside S7–S10.

## Browser Monitor

The existing private browser page remains available when networking is present. It shows:

- Live annotated camera stream
- Search, acquire, lock, lost, and fault state
- Detected pad center and active ring
- Current S7–S10 PWM commands
- Camera processing frame rate
- Fault reason and MAVLink health
- A `Stop and neutral` control

Closing the browser or losing Wi-Fi does not stop guidance. The browser is not part of the control loop.

## Logging

Record a bounded local log with timestamps for:

- Service startup and shutdown
- Flight-controller connection and parameter validation
- State transitions
- Target center, selected zone, and commanded PWM values at a reduced logging rate
- Target loss and reacquisition
- Faults and neutral commands

Logs must rotate so they cannot fill the Pi's storage.

## Verification Plan

### Automated tests

- Every state transition, including acquisition and loss timing
- Three-frame lock requirement
- False one-frame detection rejection
- Zone selection and hysteresis
- Horizontal, vertical, and diagonal servo mapping
- Full ±400 µs request and per-servo limiting
- Stale frame, missing target, command rejection, and heartbeat-loss neutral behavior
- Shutdown and exception cleanup
- Browser status without control-loop dependency

### Hardware-in-the-loop bench tests

Use a restrained rocket with the motor or ignition circuit disconnected:

1. Boot without Wi-Fi and verify automatic startup and searching.
2. Boot without the pad and verify all fins remain neutral.
3. Move the pad into view and verify lock after three consistent detections.
4. Move the pad through all four image directions and diagonal positions at a temporary ±200 µs cap.
5. Repeat through every camera ring at the final ±400 µs cap.
6. Center the pad and verify all fins return to their calibrated neutrals while lock remains active.
7. Remove the pad and verify neutral within 0.5 seconds.
8. Disconnect the camera and flight controller separately and verify neutral/fault behavior.
9. Terminate and restart the service and verify neutral cleanup followed by automatic recovery.
10. Power-cycle the complete assembly and repeat the critical neutral and acquisition checks.

### Suspended and drop tests

After the complete bench sequence passes, use recorded low-height suspended or drop tests to verify the signs and scale of actual camera motion. Aerodynamic steering direction and stability must be established from these measurements before any launch test relies on autonomous guidance.

## References

- ArduPilot Companion Computers: https://ardupilot.org/plane/docs/common-companion-computers.html
- ArduPilot Servo control: https://www.ardupilot.ardupilot.org/plane/docs/common-servo.html
- Existing servo map: `outputs/servo-map.md`
- Existing camera setup: `outputs/pi-camera-setup.md`
