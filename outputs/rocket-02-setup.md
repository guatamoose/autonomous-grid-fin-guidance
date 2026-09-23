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
- `rocket-guidance.service` is installed in observe-only configuration.
- The service is disabled and inactive until Rocket 2 is calibrated.
- Post-reboot power status during setup: `throttled=0x0`.
- Local source verification before profile deployment: 105 tests passed.
- The deployed Python files passed compilation after reboot.
- The Rocket 2 profile was deployed on 2026-09-23 and selected through
  `GUIDANCE_AIRFRAME_PROFILE`.
- The deployed controller and profile checksums matched the tested local files.
- The guidance service remained disabled and inactive after deployment.

## Hardware still to verify

- The Pi camera was not detected during initial setup (`No cameras available`),
  then was detected after profile deployment as an IMX219 camera.
- A passive check received no bytes from the flight controller at either 57600
  or 115200 baud. Confirm flight-controller power and its telemetry-port wiring
  before attempting parameter readback.
- The saved flight-controller values must be read back before servo power is
  restored.
- The fins moved unexpectedly at power-up on 2026-09-23. The provisional
  neutral values below are therefore unverified until a restrained bench check.

## Airframe map

Use the rear view of the rocket with the camera at the top. Record the actual
channel connected to each position before enabling guidance.

| Physical fin | Rocket 1 reference | Rocket 2 channel |
| --- | --- | --- |
| Top | S8 | S7 |
| Right | S7 | S8 |
| Bottom | S9 | S9 |
| Left | S10 | S10 |

## Rocket 2 servo calibration

These values were entered for Rocket 2 and are encoded in its software profile.
They are provisional because the fins moved unexpectedly on the next power-up.

| Channel | Physical fin | Minimum | Neutral | Maximum | Direction sign verified |
| --- | --- | ---: | ---: | ---: | --- |
| S7 | Top | 1120 | 1520 | 1920 | Provisional |
| S8 | Right | 1050 | 1450 | 1850 | Provisional |
| S9 | Bottom | 1185 | 1585 | 1985 | Provisional |
| S10 | Left | 880 | 1280 | 1680 | Provisional |

At each channel's Low setting, the observed edge moving toward the nose was:
S7 top left edge, S8 right top edge, S9 bottom right edge, and S10 left bottom
edge. Opposing physical fins therefore require opposite PWM signs so that their
grid surfaces tilt together.

The selected software mixing is top S7 opposite bottom S9 for horizontal image
error, and right S8 opposite left S10 for vertical image error. The profile
supports the complete tested request range of up to 400 microseconds from each
provisional neutral, bounded by the listed channel limits.

## Activation gate

Keep `rocket-guidance.service` disabled until all of the following are true:

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
