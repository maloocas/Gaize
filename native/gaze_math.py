"""Pure gaze geometry and calibration helpers."""

from __future__ import annotations

import math
import statistics


LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)


def _distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def mean_ear(points):
    values = []
    for ids in (LEFT_EYE, RIGHT_EYE):
        p = [points[i] for i in ids]
        width = _distance(p[0], p[3])
        if width > 1e-6:
            values.append((_distance(p[1], p[5]) + _distance(p[2], p[4])) / (2 * width))
    return sum(values) / len(values) if values else None


def iris_ratio(points):
    """Return iris position relative to the eye itself, reducing head movement."""
    if len(points) < 478:
        return None
    def center(ids):
        return (sum(points[i].x for i in ids) / len(ids),
                sum(points[i].y for i in ids) / len(ids))
    def ratio(iris, outer, inner, top, bottom):
        dx = points[inner].x - points[outer].x
        dy = points[bottom].y - points[top].y
        if abs(dx) < 1e-6 or abs(dy) < 1e-6:
            raise ValueError("degenerate eye landmarks")
        return ((iris[0] - points[outer].x) / dx,
                (iris[1] - points[top].y) / dy)
    try:
        left = ratio(center((468, 469, 470, 471, 472)), 33, 133, 159, 145)
        right = ratio(center((473, 474, 475, 476, 477)), 362, 263, 386, 374)
    except ValueError:
        return None
    return ((left[0] + right[0]) / 2, (left[1] + right[1]) / 2)


class GazeCalibration:
    """Piecewise linear calibration that maps a user's eye range to all edges."""

    def __init__(self, samples):
        # Samples are (raw_x, raw_y, target_x, target_y), normalized.
        if len(samples) < 5:
            raise ValueError("at least five calibration points are required")
        self.left = statistics.median(s[0] for s in samples if s[2] <= .15)
        self.center_x = statistics.median(s[0] for s in samples if .35 <= s[2] <= .65)
        self.right = statistics.median(s[0] for s in samples if s[2] >= .85)
        self.top = statistics.median(s[1] for s in samples if s[3] <= .15)
        self.center_y = statistics.median(s[1] for s in samples if .35 <= s[3] <= .65)
        self.bottom = statistics.median(s[1] for s in samples if s[3] >= .85)
        if min(abs(self.center_x-self.left), abs(self.right-self.center_x),
               abs(self.center_y-self.top), abs(self.bottom-self.center_y)) < .008:
            raise ValueError("eye movement range was too small; keep your head still and follow each dot")

    @staticmethod
    def _axis(value, start, center, end):
        # Works whether the camera's horizontal signal is mirrored or not.
        first_half = value <= center if start < end else value >= center
        if first_half:
            result = .5 * (value-start) / (center-start)
        else:
            result = .5 + .5 * (value-center) / (end-center)
        return max(0.0, min(1.0, result))

    def map(self, raw_x, raw_y):
        x = self._axis(raw_x, self.left, self.center_x, self.right)
        y = self._axis(raw_y, self.top, self.center_y, self.bottom)
        return x, y
