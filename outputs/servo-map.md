# Grid-fin servo map

Reference: positions as viewed relative to the camera, using the orientation identified during bench testing on 2026-09-16. In the assembly photo, the nose rests on the table, and the planned camera position is by the user's thumb, facing toward the landing pad.

| Flight-controller output | Servo position | Intended steering pair |
| --- | --- | --- |
| S7 | Right of camera | Up/down in camera view, paired with S10 |
| S8 | Above camera | Left/right in camera view, paired with S9 |
| S9 | Below camera | Left/right in camera view, paired with S8 |
| S10 | Left of camera | Up/down in camera view, paired with S7 |

All four outputs were commanded individually with the controller disarmed and fins removed. The replacement servo on S7 moved during the 1750 us bench test; the original servo or its lead was likely faulty. The other three servos also moved during individual tests. All tests returned outputs to 1500 us.

With the fins installed, each output S7-S10 was tested individually from 1500 to 1600 us and back. The user observed smooth movement without binding or buzzing on all four fins.

The table records physical positions and intended control pairs. Required servo reversal and actual aerodynamic response have not yet been verified.

Direction observations from the same butt-end view at 1600 us:

| Output | Fin position | Observed top-edge motion |
| --- | --- | --- |
| S7 | Right | Away from computer, toward planned camera position |
| S10 | Left | Toward computer |
| S8 | Top | Right edge moved toward computer |
| S9 | Bottom | Left edge moved toward computer |

The user corrected an initial misidentification of S10 as right; S10 is left. All four directions above are observations at 1600 us from the butt-end view. The required servo reversals, coordinated pair commands, and actual aerodynamic response still need verification.

## Paired bench direction test

After electronic neutral calibration, these pairs were commanded 200 µs either side of their individual centers while the FC was disarmed:

| Pair | One direction | Reverse direction | User observation |
| --- | --- | --- | --- |
| Top S8 / bottom S9 | S8=1630, S9=1400 | S8=1230, S9=1800 | Same recorded pair signs, recalculated around the repaired-fin neutrals |
| Right S7 / left S10 | S7=1705, S10=1200 | S7=1305, S10=1600 | Same recorded pair signs, recalculated around the repaired-fin neutrals |

After the fin repair on 2026-09-22, the individual neutral PWM values are
S7=1505, S8=1430, S9=1600, and S10=1400 µs. The flight controller parameters
were read back and all four outputs were commanded to those values. Matching
`SERVO_OUTPUT_RAW` telemetry was received.

This establishes relative PWM signs for coordinated fin motion on the bench: within each opposite pair, one output increases while the other decreases. It does not establish which command moves the rocket left/right or up/down in free flight, nor whether equal PWM offsets give equal fin angles or forces.

## Expected steering sign from visual inspection

The user inspected the paired deflections and identified the **expected nose movement** when viewed from behind the rocket looking toward the landing pad:

| Expected nose direction | S7 right | S8 top | S9 bottom | S10 left |
| --- | ---: | ---: | ---: | ---: |
| Left | 1505 | 1630 | 1400 | 1400 |
| Right (reverse of left) | 1505 | 1230 | 1800 | 1400 |
| Up | 1705 | 1430 | 1600 | 1200 |
| Down (reverse of up) | 1305 | 1430 | 1600 | 1600 |

The left and up rows were visually identified by the user at the shown ±200 µs test positions. The right and down rows are their reverse commands, inferred from the symmetric bench movements. These are steering hypotheses, not measured rocket trajectory or camera-image motion. All four outputs were returned to neutral after the demonstrations and verified by telemetry.
