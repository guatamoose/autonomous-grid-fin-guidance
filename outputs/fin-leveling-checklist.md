# Grid-fin neutral alignment

Reference: view from the camera end, with the rocket's long axis as the straight-ahead line. A neutral fin is aligned with the rocket body, regardless of how the rocket is tilted relative to the ground.

The saved flight-controller parameters have `SERVO7_TRIM` through `SERVO10_TRIM` at **1500 µs**, `MIN` at **1100 µs**, `MAX` at **1900 µs**, `REVERSED` at **0**, and `SERVO_RATE` at **50 Hz**. The four outputs are mapped as follows:

| Output | Fin position | Neutral offset at 1500 µs | Final trim | +100 µs observed direction |
| --- | --- | --- | --- | --- |
| S7 | Right of camera | To measure | To set | Away from computer in earlier bench view |
| S8 | Above camera | To measure | To set | Right edge toward computer in earlier bench view |
| S9 | Below camera | To measure | To set | Left edge toward computer in earlier bench view |
| S10 | Left of camera | To measure | To set | Toward computer in earlier bench view |

## Before powering the servos

1. Label the fins S7, S8, S9, and S10 on the body using the table above. Mark the rocket's long axis beside each fin so there is a fixed straight-ahead reference.
2. Check that each fin and linkage moves freely by hand without forcing the servo gearbox. Look for a bent linkage or horn that cannot reach a straight neutral position.
3. Keep the rocket secured on the bench, clear of the fins. Keep any propulsion or deployment hardware disconnected during this calibration.

## Once servo power is available

1. Power the flight controller and servo supply. Command each output to **1500 µs**, one at a time, and confirm it holds steady.
2. Compare the fin's plane with the marked rocket axis using a straightedge or angle gauge held at the same place for all four fins. Record the signed offset in the table.
3. If a fin is visibly off, first center it mechanically at 1500 µs by adjusting its horn or linkage. Use small `SERVOn_TRIM` changes for the remaining offset, recording each final value. ArduPilot's Plane guide recommends mechanical correction if trim needs to move more than roughly 50 µs from 1500.
4. Repeat the neutral measurement after cycling each fin slightly to both sides and returning to trim. Check for backlash, binding, or a fin that does not return to the same position.
5. Test S7/S10 and S8/S9 as pairs with small, equal commands around their measured neutrals. Record which output needs reversal to produce the intended common motion in the camera view. Return all four to neutral after each test.

The earlier ±100 µs movement tests showed that all four servos move smoothly, but they did not establish neutral alignment or paired direction. No camera-based fin control has been enabled.

## Servo/Relay test values observed later

On the Mission Planner Servo/Relay tab, shifting each row's Low and High fields produced these temporary Mid commands while the user judged the fins straight:

| Output | Test Low | Test High | Test Mid |
| --- | ---: | ---: | ---: |
| S7 | 1105 | 1905 | 1505 |
| S8 | 1060 | 1860 | 1460 |
| S9 | 970 | 1770 | 1370 |
| S10 | 800 | 1600 | 1200 |

Live telemetry confirmed those outputs, but at that time the controller's stored `SERVOn_MIN`, `SERVOn_MAX`, and `SERVOn_TRIM` remained 1100, 1900, and 1500 on all four channels. These Servo/Relay test fields were not a persistent trim calibration. S9 and S10 were far from 1500, so their available travel required separate verification.

On a later pass, the visually centered temporary outputs were S7=1505, S8=1460, S9=1370, and S10=1200 µs. S10 was subsequently returned to 1500 µs and verified by telemetry before power to the servos was removed. The user reported that its horn/fin assembly cannot be removed from the servo spline in the current mount.

The user chose an electronic bench neutral. The controller now has `SERVO7_TRIM=1505`, `SERVO8_TRIM=1460`, `SERVO9_TRIM=1370`, and `SERVO10_TRIM=1200`; readback after an FC reboot confirmed all four. At reboot, live PWM on S7–S10 was zero until `MAV_CMD_DO_SET_SERVO` was sent; the trim parameters did not themselves drive the unassigned (`FUNCTION=0`) outputs. The four saved neutral PWM values were then commanded and confirmed by live output telemetry.

After the reboot and neutral commands, the user confirmed all four fins appeared straight and held without buzzing or binding.

The user clarified that S10 was physically tested at 800 µs and moved smoothly without buzzing, binding, or contact with the rocket body. It had also been tested at 1600 µs earlier. Therefore `SERVO10_MIN=800` and `SERVO10_MAX=1600` were saved and read back, making its 1200 µs trim the midpoint of the configured PWM range. This establishes equal PWM headroom on either side, not equal fin angle or aerodynamic force; paired direction and travel still need bench verification. S7–S9 retain their saved 1100–1900 µs limits.

## Repaired-fin calibration — 2026-09-22

After repairing the fin assembly, the user selected these new centered ranges:

| Output | Minimum | Neutral | Maximum |
| --- | ---: | ---: | ---: |
| S7 | 1105 | 1505 | 1905 |
| S8 | 1030 | 1430 | 1830 |
| S9 | 1200 | 1600 | 2000 |
| S10 | 1000 | 1400 | 1800 |

All four channels retain symmetric ±400 µs travel. The parameters were written
with the controller disarmed and guidance stopped, read back independently, and
then commanded once at neutral. Telemetry matched all four requested neutral
values. The user then confirmed that all four fins were straight, quiet, and
clear of binding.
