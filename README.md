# Autonomous Grid-Fin Landing Guidance

Prototype guidance software for a Raspberry Pi Zero 2 W, Raspberry Pi AI Camera,
Matek H743-SLIM V4 flight controller, and four SG90 grid-fin servos.

## Current capabilities

- Detects the orange landing pad and steers its center toward the camera center.
- Uses a 5% dead zone and 100 / 200 / 300 / 400 microsecond correction bands.
- Drives the calibrated S7-S10 fin channels through a bounded MAVLink interface.
- Starts at boot, provides a browser monitor, and records one-minute evidence clips.
- Includes bench simulations, hardware fault handling, and deployment files.
- Supports highlight-protected camera auto-exposure with an adjustable EV bias.

## Verification

Run the complete test suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

The camera exposure update was verified with 94 passing tests on 2026-09-21.

## Repository contents

- `src/` — guidance, detection, camera overlay, recording, and servo control
- `tests/` — automated behavior and deployment tests
- `deploy/` — systemd service, defaults, and log rotation
- `scripts/` — installation and visualization helpers
- `docs/` — design specifications and implementation plans
- `outputs/` — operating notes, calibration records, field review, model files, and final presentation

Raw flight videos, generated contact sheets, local environments, SSH keys, and
temporary deployment copies are intentionally excluded from Git. Their hashes
are recorded in `outputs/recordings-manifest.sha256`.
