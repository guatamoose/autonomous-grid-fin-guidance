# Flight video review — 2026-09-21

## Requested recording

`guidance-20260921T120242Z-55c2.mp4`

- 60.0 seconds, 900 frames, 15 FPS, 640×480.
- The camera remains pointed generally toward the ground while the view slowly
  rotates over grass, brush, and a light-colored road.
- The image suggests a controlled downward-looking attitude with continuous
  roll rather than a fast end-over-end tumble.
- The guidance overlay remains `SEARCHING` for the entire recording.
- No orange-pad bounding box or confirmed lock appears in any frame.
- Requested correction remains `0 us`.
- Servo values remain at their calibrated neutral positions for the entire clip:
  S7 1505, S8 1460, S9 1370, S10 1200.
- Recorded guidance processing is approximately 11.5 FPS and recording remains
  active.

The largest frame-to-frame changes in the top pad-status bar and the servo line
were only normal H.264 compression variation. A full 900-frame scan found no
brief detection or fin command between the five-second contact-sheet samples.

## Adjacent recordings

`guidance-20260921T120142Z-55c2.mp4`

- The preceding 60-second recording shows the same airborne, downward-looking,
  slowly rotating view.
- It also remains `SEARCHING` with all four outputs neutral for all 900 frames.

`guidance-20260921T120342Z-55c2.mp4`

- This following segment is 10,489,856 bytes but is incomplete.
- The MP4 `moov` index is missing, consistent with recording being interrupted
  before the segment closed. Standard players cannot open it as copied.

`guidance-20260921T120442Z-55c2.mp4`

- This was the newest active segment and is zero bytes on the powered-off card.

## Likely reason no lock occurred

The orange pad is not visibly identifiable in the reviewed footage. If the small
dark object beside the road is the pad, it is both the wrong apparent color and
too small at that altitude for the current detector. The detector requires a
plausible orange rectangular region covering at least 0.2% of the sampled image,
roughly equivalent to a contiguous 25×25-pixel square in a 640×480 frame before
shape and fill checks.

## Copied evidence

- `guidance-20260921T120142Z-55c2.mp4`
- `guidance-20260921T120242Z-55c2.mp4`
- `guidance-20260921T120342Z-55c2.mp4`
- `guidance-20260921T120142Z-55c2-contact-sheet.png`
- `guidance-20260921T120242Z-55c2-contact-sheet.png`
- Detection-diagnostic contact sheets for both complete videos.

The source SD partition was mounted read-only. After copying, it was detached
from WSL and returned to its original Windows-only state.
