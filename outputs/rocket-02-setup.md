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
- Local source verification before deployment: 97 tests passed.
- The deployed Python files passed compilation after reboot.

## Hardware still to verify

- The Pi camera was not detected during initial setup (`No cameras available`).
- Flight-controller UART communication has not been tested on Rocket 2.
- Physical S7-S10 fin positions are not recorded yet.
- Servo minimum, neutral, and maximum values are not calibrated yet.
- Fin movement signs for camera left, right, up, and down are not recorded yet.

## Airframe map

Use the rear view of the rocket with the camera at the top. Record the actual
channel connected to each position before enabling guidance.

| Physical fin | Rocket 1 reference | Rocket 2 channel |
| --- | --- | --- |
| Top | S8 | Unknown |
| Right | S7 | Unknown |
| Bottom | S9 | Unknown |
| Left | S10 | Unknown |

## Rocket 2 servo calibration

Do not copy Rocket 1 values into this table. Center and verify each Rocket 2
servo independently.

| Channel | Physical fin | Minimum | Neutral | Maximum | Direction sign verified |
| --- | --- | ---: | ---: | ---: | --- |
| S7 | Unknown | Unknown | Unknown | Unknown | No |
| S8 | Unknown | Unknown | Unknown | Unknown | No |
| S9 | Unknown | Unknown | Unknown | Unknown | No |
| S10 | Unknown | Unknown | Unknown | Unknown | No |

## Activation gate

Keep `rocket-guidance.service` disabled until all of the following are true:

1. The camera appears in `rpicam-hello --list-cameras`.
2. The flight controller produces a MAVLink heartbeat on `/dev/serial0` at
   57600 baud.
3. S7-S10 are mapped to their physical fin positions.
4. Each fin is mechanically centered and its safe minimum, neutral, and maximum
   values are saved and read back.
5. Both opposite-fin pairs move together in the intended camera direction.
6. Rocket 2's map and calibration are loaded into the guidance software.
7. Observe-only mode is verified before any restrained live movement test.
