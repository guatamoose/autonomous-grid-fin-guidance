# Rocket 2 setup record

Updated: 2026-09-23

## Computer and Pi identity

- Hostname: `rocket-02`
- Hotspot address during setup: `192.168.137.225`
- Wi-Fi MAC address: `88:a2:9e:c4:b6:62`
- SSH user: `pi`
- Dedicated local key: `C:\Users\remote.admin\.ssh\rocket02_ed25519`
- Operating system: Raspberry Pi OS Legacy Lite 64-bit (Bookworm)
- Architecture: `aarch64`

## Installed guidance base

- Application directory: `/home/pi/rocket`
- Python environment: `/home/pi/rocket/venv`
- MAVLink library: `pymavlink 2.4.49`
- Camera, NumPy, Pillow, serial, and FFmpeg packages are installed.
- Hardware UART is enabled and `/dev/serial0` resolves to `/dev/ttyS0`.
- `rocket-guidance.service` is installed, enabled at boot, and still configured
  for observe-only operation.
- Post-reboot power status during setup: `throttled=0x0`.
- Local source verification before profile deployment: 105 tests passed.
- The deployed Python files passed compilation after reboot.
- The Rocket 2 profile was deployed on 2026-09-23 and selected through
  `GUIDANCE_AIRFRAME_PROFILE`.
- The deployed controller and profile checksums matched the tested local files.
- A full cold-power test reached active camera guidance at about 31 seconds,
  with zero service restarts and no recorded power throttling.

## Hardware verification completed

- The Pi camera is detected as an IMX219 camera.
- The Pi is wired to the flight controller's TX1/RX1 UART.
- Flight-controller `SERIAL1_PROTOCOL=2`, `SERIAL1_BAUD=57`, and
  `SERIAL1_OPTIONS=0` were saved and survived a controller reboot.
- The Pi received valid MAVLink on `/dev/serial0` at 57600 baud and read back
  every S7-S10 function, minimum, trim, and maximum value.
- S7-S10 use function 0 so the Pi can command them with
  `MAV_CMD_DO_SET_SERVO`. They produce no PWM until commanded after power-up.
- The service sends the four neutral values before it opens the camera. On a
  cold boot, the fins settle to neutral once the Pi establishes MAVLink; they
  then remain stable.

## Airframe map

Use the rear view of the rocket with the camera at the top.

| Physical fin | Rocket 1 reference | Rocket 2 channel |
| --- | --- | --- |
| Top | S8 | S7 |
| Right | S7 | S8 |
| Bottom | S9 | S9 |
| Left | S10 | S10 |

## Rocket 2 servo calibration

These values are saved in the flight controller, encoded in Rocket 2's software
profile, and were read back through both USB and the Pi UART.

| Channel | Physical fin | Minimum | Neutral | Maximum | Direction sign verified |
| --- | --- | ---: | ---: | ---: | --- |
| S7 | Top | 1120 | 1520 | 1920 | Verified |
| S8 | Right | 1050 | 1450 | 1850 | Verified |
| S9 | Bottom | 1185 | 1585 | 1985 | Verified |
| S10 | Left | 880 | 1280 | 1680 | Verified |

At each channel's Low setting, the observed edge moving toward the nose was:
S7 top left edge, S8 right top edge, S9 bottom right edge, and S10 left bottom
edge. Opposing physical fins therefore require opposite PWM signs so that their
grid surfaces tilt together.

The selected software mixing is top S7 opposite bottom S9 for horizontal image
error, and right S8 opposite left S10 for vertical image error. The profile
supports the complete tested request range of up to 400 microseconds from each
neutral, bounded by the listed channel limits. Both opposing-fin pairs completed
the full positive and negative 400-microsecond tests smoothly and returned to
neutral without binding or buzzing.

## Stability checks

- Two minutes of repeated neutral commands completed without fin movement.
- Camera detection at 15 FPS with recording off completed without fin movement.
- Camera exposure compensation was restored to the normal `0.0` setting after
  negative compensation made the indoor camera view too dark.
- Camera detection with recording on crossed multiple 60-second recording
  boundaries without fin movement.
- The real systemd service ran for more than two minutes without fin movement,
  restarts, errors, or power throttling.
- A Pi-only reboot and a complete battery cold start each started the service
  once and remained stable. The complete cold start required about 31 seconds
  before guidance became active.
- The only observed cold-start movement was the fins settling to their saved
  neutral positions when the Pi first commanded the function-0 outputs.

## Activation gate

The installation and observe-only gates below have passed:

1. The camera appears in `rpicam-hello --list-cameras`.
2. The flight controller produces a MAVLink heartbeat on `/dev/serial0` at
   57600 baud.
3. S7-S10 are mapped to their physical fin positions.
4. Each fin is mechanically centered and its safe minimum, neutral, and maximum
   values are saved and read back.
5. Both opposite-fin pairs move together in the intended camera direction.
6. Rocket 2's map and calibration are loaded into the guidance software using
   `/etc/rocket-guidance/airframes/rocket-02.json`.
7. Observe-only mode is verified before any restrained live movement test.

The remaining gate is the first active camera-steering test. Keep the rocket
restrained, hands clear, and any motor or ignition circuit disconnected before
removing `--observe-only`. Confirm that the pad's image-space direction produces
the intended paired fin response, then return the fins to neutral.
