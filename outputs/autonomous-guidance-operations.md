# Autonomous landing-pad guidance operations

## Current verified state — 2026-09-22

- Host: `rocketpi` (`pi@192.168.137.104` on the Windows hotspot)
- Application: `/home/pi/rocket`
- Service: `rocket-guidance.service`
- Boot enablement: enabled
- Runtime state: active in live guidance mode after the repaired-fin calibration.
- Startup mode: live guidance starts automatically when the Pi boots.
- Calculated correction cap: ±400 microseconds
- S7–S10 stay at their calibrated neutral values while no pad is detected. After a confirmed pad lock, the live outputs follow the calculated correction immediately.
- Camera: IMX500 detected and processing 640×480 guidance frames.
- Post-reconnection check: approximately 11 FPS, recording active, no recording
  error, and all four outputs held at the new neutral values while searching.
- Guidance performance with recording active: 70/70 valid one-second
  samples, 11.757 FPS minimum, 11.882 FPS median, and 11.869 FPS mean.
- Recorder: H.264 hardware encoding at 640×480 and 15 FPS in one-minute
  segments. The newest 60 completed segments are retained, giving one hour of
  rolling evidence plus the active segment.
- Servo transport: changed commands only, capped at 12 Hz, with sequential
  acknowledgement and up to three MAVLink delivery attempts. Camera processing
  and recording run independently of acknowledged serial traffic.
- Restrained live activation: the service acquired a moving pad and exercised
  the 100, 200, 300, and 400 microsecond correction bands. It returned all four
  outputs to neutral when the pad left view. The service remained active with
  zero restarts and the Pi reported `throttled=0x0`.
- Power-up behavior was verified with a Pi reboot. About 97 seconds after boot,
  the enabled service was active with zero restarts, live mode and the ±400
  microsecond cap loaded, recording active, and S7–S10 neutral while searching.
  The current boot journal contained no guidance errors.
- Monitor: `http://192.168.137.104:8766/`

## Calibrated outputs

| Output | Minimum | Neutral | Maximum |
| --- | ---: | ---: | ---: |
| S7 | 1105 | 1505 | 1905 |
| S8 | 1030 | 1430 | 1830 |
| S9 | 1200 | 1600 | 2000 |
| S10 | 1000 | 1400 | 1800 |

These values were written to the disarmed flight controller on 2026-09-22,
read back independently, and then commanded once. `SERVO_OUTPUT_RAW` telemetry
matched S7=1505, S8=1430, S9=1600, and S10=1400. The user confirmed that all
four fins were straight, quiet, and clear of binding at those positions.

## Service commands on the Pi

```sh
sudo systemctl start rocket-guidance
sudo systemctl stop rocket-guidance
sudo systemctl restart rocket-guidance
systemctl status rocket-guidance --no-pager
journalctl -u rocket-guidance -n 100 --no-pager
tail -n 100 /home/pi/rocket/logs/guidance.log
curl -s http://127.0.0.1:8766/state
```

Stopping the service invokes the runtime cleanup, which attempts to command all four outputs to neutral before closing the MAVLink connection.

## Observe-only mode

Set `/etc/default/rocket-guidance` to:

```ini
GUIDANCE_MAX_OFFSET=400
GUIDANCE_MODE_ARG=--observe-only
```

Then restart the service:

```sh
sudo systemctl restart rocket-guidance
```

Observe-only continues to calculate and display the full ±400 microsecond
correction while the real S7–S10 outputs remain at their calibrated neutral
values.

## Recording

Recordings are stored in:

```text
/home/pi/rocket/recordings
```

Each completed file is a one-minute MP4 containing the camera image, steering
rings, pad detection and lock annotation, requested correction, S7–S10 values
and signed offsets, mode, measured FPS, recording state, and UTC timestamp.

Example inspection commands:

```sh
ls -lh /home/pi/rocket/recordings/guidance-*.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,avg_frame_rate \
  -show_entries format=duration,size -of json \
  /home/pi/rocket/recordings/guidance-*.mp4
```

Verified evidence copied to the workspace:

```text
outputs/guidance-evidence-20260921T045509Z.mp4
outputs/guidance-evidence-frame.png
```

## Live mode

Live mode must only be enabled during the restrained hardware activation procedure, with hands clear, the flight controller disarmed, and motor and ignition circuits disconnected.

Set `/etc/default/rocket-guidance` to:

```ini
GUIDANCE_MAX_OFFSET=400
GUIDANCE_MODE_ARG=
```

The installed service uses this configuration now. It starts at boot, searches
continuously, locks after the configured acquisition checks, and commands up to
±400 microseconds according to the camera zone.

The systemd unit deliberately expands the optional final argument as
`$GUIDANCE_MODE_ARG`. Braced expansion passes an empty argument to Python when
live mode is selected and must not be restored.

## Emergency neutral

From the Pi:

```sh
sudo systemctl stop rocket-guidance
```

From the local monitor while the service is reachable:

```sh
curl -X POST http://127.0.0.1:8766/stop
```

The monitor stop action latches `INHIBITED` and neutral until the service is restarted.

## Backup and recovery

The pre-installation application directory is preserved at:

```text
/home/pi/rocket-backups/before-autonomous-20260920-01
```

The original pre-recording deployment is preserved at:

```text
/home/pi/rocket-backups/before-high-fps-recording-20260921T043124Z
```

The final checksum-verified live deployment package remains at:

```text
/home/pi/pi-guidance-deploy-20260921T050526Z
```
