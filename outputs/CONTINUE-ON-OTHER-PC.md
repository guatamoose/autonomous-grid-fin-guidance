# Continue rocket guidance work on another computer

## Current state

- Native always-on Raspberry Pi guidance implementation is complete locally through deployment packaging.
- The complete local test suite passes: 64 tests, zero failures.
- Final configured guidance cap is ±400 microseconds from each calibrated neutral.
- Initial Pi deployment is intentionally observe-only and forces all physical outputs to neutral.
- The original Pi SSH public key is accepted by the Pi, but its private-key passphrase is unavailable.
- No replacement recovery key has been installed on the Pi yet.

## Hardware and service settings

- Pi: Raspberry Pi Zero 2 W
- Camera: Raspberry Pi AI Camera / IMX500
- Flight controller: Matek H743-SLIM V4 running ArduPlane
- Pi UART: `/dev/serial0` at 57600 baud
- Last hotspot address: `192.168.137.104` (may change)
- Monitor port: 8766
- Servo calibration:
  - S7 right: 1105 / 1505 / 1905
  - S8 top: 1060 / 1460 / 1860
  - S9 bottom: 970 / 1370 / 1770
  - S10 left: 800 / 1200 / 1600

## First task on the other computer

1. Generate a new Ed25519 recovery key on that computer. Do not copy or depend on the old passphrase-protected key.
2. Power off the Pi and insert its microSD card.
3. Mount the Linux root partition safely, preferably through WSL if Windows does not expose it.
4. Back up `/home/pi/.ssh/authorized_keys`, then append only the new public key. Preserve ownership `pi:pi`, directory mode `700`, and file mode `600`.
5. Unmount/eject the card cleanly, put it back in the Pi, power the Pi, and verify SSH with the new key.
6. Preserve timestamped backups of existing `/home/pi/rocket` files before deployment.
7. Run all local tests from the extracted folder:

   `python -m unittest discover -s tests -v`

8. Copy `src`, `deploy`, and `scripts/install_guidance_service.sh` to a staging folder on the Pi.
9. Run `bash -n scripts/install_guidance_service.sh` on the Pi.
10. Install and start only the observe-only configuration first. Do not enable live servo movement unattended.

## Observe-only verification

- Verify systemd is enabled and active.
- Verify `/state` advances with no browser client.
- Verify search, acquire, lock, lost, and stale-camera behavior.
- Confirm reported physical output values remain neutral:
  - S7 1505
  - S8 1460
  - S9 1370
  - S10 1200
- Verify logs rotate and `vcgencmd get_throttled` reports `0x0`.

## Work requiring the user present

- Restrained temporary ±200 live movement test
- Stop-and-neutral latch test
- Camera and MAVLink fault tests involving physical disconnection
- Final full ±400 live test
- Complete electronics power-cycle test

Before movement: rocket restrained, hands clear, motor/ignition disconnected, flight controller disarmed, and servo power connected only for the supervised test.

## Important files

- Design: `docs/superpowers/specs/2026-09-20-always-on-pad-guidance-design.md`
- Implementation plan: `docs/superpowers/plans/2026-09-20-always-on-pad-guidance.md`
- Runtime: `src/autonomous_guidance.py`
- Servo control: `src/servo_controller.py`
- Monitor: `src/guidance_web.py`
- systemd package: `deploy/`
- Installer: `scripts/install_guidance_service.sh`
- Test suite: `tests/`
- Verification record: `work/verification-log.md`
