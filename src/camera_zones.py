"""Camera-center zones for a landing-pad preview.

This module calculates requested steering direction and magnitude only. It does
not detect the pad, talk to the flight controller, or command servos.
"""

from dataclasses import dataclass
from math import hypot, isfinite

DEAD_ZONE_RADIUS = 0.05
RING_RADII = (0.25, 0.50, 0.75)
RING_REQUESTS_US = (100, 200, 300, 400)


@dataclass(frozen=True)
class ZoneDecision:
    target_seen: bool
    radius_fraction: float
    requested_us: int
    safe_us: int
    nose_x_us: float
    nose_y_us: float
    safe_nose_x_us: float
    safe_nose_y_us: float


def decide(target_center, frame_size, max_tested_us=200):
    """Return a proposed nose-direction vector from a target's pixel center.

    The radius is measured against half the frame's shorter dimension, so the
    zones are circles in the image. +X means image right, +Y means image up.
    The `safe_*` fields cap the requested vector at the bench-tested offset.
    None means no target and returns zero correction.
    """
    width, height = frame_size
    if width <= 0 or height <= 0 or max_tested_us < 0:
        raise ValueError("Invalid frame size or tested servo offset")
    if target_center is None:
        return ZoneDecision(False, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0)

    x, y = target_center
    if not (isfinite(x) and isfinite(y) and 0 <= x < width and 0 <= y < height):
        raise ValueError("Target center must be a finite point within the frame")

    dx, dy = x - width / 2, height / 2 - y
    distance = hypot(dx, dy)
    radius_fraction = distance / (min(width, height) / 2)
    if radius_fraction <= DEAD_ZONE_RADIUS:
        requested = 0
    elif radius_fraction <= RING_RADII[0]:
        requested = RING_REQUESTS_US[0]
    elif radius_fraction <= RING_RADII[1]:
        requested = RING_REQUESTS_US[1]
    elif radius_fraction <= RING_RADII[2]:
        requested = RING_REQUESTS_US[2]
    else:
        requested = RING_REQUESTS_US[3]

    safe = min(requested, max_tested_us)
    if requested == 0:
        return ZoneDecision(True, radius_fraction, 0, 0, 0.0, 0.0, 0.0, 0.0)
    unit_x, unit_y = dx / distance, dy / distance
    return ZoneDecision(
        True, radius_fraction, requested, safe,
        requested * unit_x, requested * unit_y,
        safe * unit_x, safe * unit_y,
    )


def decide_with_hysteresis(target_center, frame_size, previous_requested_us,
                           margin=0.03, max_tested_us=200):
    """Return a zone decision while resisting chatter at ring boundaries."""
    if not 0 <= margin < 0.25:
        raise ValueError("Hysteresis margin must be between 0 and 0.25")
    raw = decide(target_center, frame_size, max_tested_us=max_tested_us)
    if not raw.target_seen or raw.requested_us == 0:
        return raw
    levels = RING_REQUESTS_US
    if previous_requested_us not in levels:
        return raw
    previous_index = levels.index(previous_requested_us)
    requested = raw.requested_us
    if requested > previous_requested_us and previous_index < len(RING_RADII):
        if raw.radius_fraction <= RING_RADII[previous_index] + margin:
            requested = previous_requested_us
    elif requested < previous_requested_us and previous_index > 0:
        if raw.radius_fraction >= RING_RADII[previous_index - 1] - margin:
            requested = previous_requested_us
    if requested == raw.requested_us:
        return raw
    vector_scale = requested / raw.requested_us
    safe = min(requested, max_tested_us)
    safe_scale = safe / raw.requested_us
    return ZoneDecision(
        True, raw.radius_fraction, requested, safe,
        raw.nose_x_us * vector_scale, raw.nose_y_us * vector_scale,
        raw.nose_x_us * safe_scale, raw.nose_y_us * safe_scale,
    )
