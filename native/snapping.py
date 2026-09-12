"""Gaze snapping onto accessibility targets, and the zoom used to choose
between several close ones.

Pure geometry on target dicts from accessibility_targets.discover_targets
({x, y, width, height, ...}, Quartz points, origin top-left).
"""

from __future__ import annotations

import math

SNAP_RADIUS = 135.0    # points from the gaze to a target's edge
ZOOM_PAD = 48.0        # context kept around the candidates when zooming
ZOOM_FILL = 0.92       # share of the screen the zoomed region fills
MAX_ZOOM = 6.0


def rect_distance(target, x, y):
    """Distance from (x, y) to the target rectangle; 0 when inside."""
    dx = max(target["x"] - x, 0.0, x - (target["x"] + target["width"]))
    dy = max(target["y"] - y, 0.0, y - (target["y"] + target["height"]))
    return math.hypot(dx, dy)


def center(target):
    return (target["x"] + target["width"] / 2, target["y"] + target["height"] / 2)


def candidates(targets, x, y, radius=SNAP_RADIUS):
    """Targets within radius of the gaze, nearest first."""
    near = [t for t in targets if rect_distance(t, x, y) <= radius]
    return sorted(near, key=lambda t: (rect_distance(t, x, y),
                                       math.dist(center(t), (x, y))))


def pick(targets, x, y):
    """The target nearest (x, y): containing rectangles first, then centers."""
    if not targets:
        return None
    return min(targets, key=lambda t: (rect_distance(t, x, y),
                                       math.dist(center(t), (x, y))))


def zoom_region(targets, screen_w, screen_h, pad=ZOOM_PAD):
    """Screen region (x, y, w, h) covering the targets, at the screen's aspect
    ratio so the zoom does not distort, and never zoomed past MAX_ZOOM."""
    left = min(t["x"] for t in targets) - pad
    top = min(t["y"] for t in targets) - pad
    right = max(t["x"] + t["width"] for t in targets) + pad
    bottom = max(t["y"] + t["height"] for t in targets) + pad
    w, h = right - left, bottom - top
    aspect = screen_w / screen_h
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    w = max(w, screen_w / MAX_ZOOM)
    h = max(h, screen_h / MAX_ZOOM)
    w, h = min(w, screen_w), min(h, screen_h)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    x = min(max(cx - w / 2, 0.0), screen_w - w)
    y = min(max(cy - h / 2, 0.0), screen_h - h)
    return (x, y, w, h)


def zoom_dest(region, screen_w, screen_h, fill=ZOOM_FILL):
    """Where the region is drawn on screen (x, y, w, h), centered."""
    scale = min(screen_w / region[2], screen_h / region[3]) * fill
    w, h = region[2] * scale, region[3] * scale
    return ((screen_w - w) / 2, (screen_h - h) / 2, w, h)


def to_zoom(target, region, dest):
    """A target rectangle in zoomed screen coordinates."""
    s = dest[2] / region[2]
    return {**target,
            "x": dest[0] + (target["x"] - region[0]) * s,
            "y": dest[1] + (target["y"] - region[1]) * s,
            "width": target["width"] * s, "height": target["height"] * s}
