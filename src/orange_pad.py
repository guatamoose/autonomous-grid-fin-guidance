"""Find a large orange rectangular patch in an RGB camera frame.

This module only reports a visual target. It never commands flight hardware.
Hue thresholds are starting values; verify them against the real pad outdoors.
"""

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter


@dataclass(frozen=True)
class Detection:
    center: tuple[int, int]
    bbox: tuple[int, int, int, int]
    area_fraction: float
    fill_fraction: float


def detect_orange_pad(frame, *, channel_order="RGB", sample_step=4,
                      min_area_fraction=0.002):
    """Return the largest plausible orange rectangle, or ``None``."""
    pixels = np.asarray(frame)
    if pixels.ndim != 3 or pixels.shape[2] != 3 or sample_step < 1:
        raise ValueError("Expected an H×W×3 camera frame and positive sample step")
    if channel_order == "BGR":
        pixels = pixels[:, :, ::-1]
    elif channel_order != "RGB":
        raise ValueError("channel_order must be RGB or BGR")

    height, width = pixels.shape[:2]
    sampled = pixels[::sample_step, ::sample_step].copy()
    hsv = np.asarray(Image.fromarray(sampled.astype(np.uint8), "RGB").convert("HSV"))
    hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    orange = (hue >= 5) & (hue <= 28) & (saturation >= 165) & (value >= 105)
    mask_image = Image.fromarray((orange.astype(np.uint8) * 255), "L")
    orange = np.asarray(mask_image.filter(ImageFilter.MaxFilter(7))
                        .filter(ImageFilter.MinFilter(7))) > 0
    rows, cols = orange.shape
    visited = np.zeros_like(orange, dtype=bool)
    minimum = max(1, int(rows * cols * min_area_fraction))
    best = None

    for seed_y, seed_x in np.argwhere(orange):
        if visited[seed_y, seed_x]:
            continue
        stack = [(int(seed_x), int(seed_y))]
        visited[seed_y, seed_x] = True
        count = 0
        left = right = int(seed_x)
        top = bottom = int(seed_y)
        while stack:
            x, y = stack.pop()
            count += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (0 <= nx < cols and 0 <= ny < rows and orange[ny, nx]
                        and not visited[ny, nx]):
                    visited[ny, nx] = True
                    stack.append((nx, ny))
        if count < minimum:
            continue
        box_width, box_height = right - left + 1, bottom - top + 1
        aspect = box_width / box_height
        fill = count / (box_width * box_height)
        if not (0.5 <= aspect <= 2.0 and fill >= 0.45):
            continue
        if best is None or count > best[0]:
            best = (count, left, top, right, bottom, fill)

    if best is None:
        return None
    count, left, top, right, bottom, fill = best
    x0, y0 = left * sample_step, top * sample_step
    x1 = min(width, (right + 1) * sample_step)
    y1 = min(height, (bottom + 1) * sample_step)
    return Detection(
        center=((x0 + x1) // 2, (y0 + y1) // 2),
        bbox=(x0, y0, x1, y1),
        area_fraction=count / (rows * cols),
        fill_fraction=fill,
    )
