"""Turn per-eye closure scores into eye gestures.

Pure and camera-free: feed one sample per frame and it returns a gesture name
when one completes. The gestures:

  * "blink"       both eyes, short and soft - a natural blink. Ignored for
                  clicking; the keyboard uses it to end a swiped word.
  * "hard_blink"  both eyes, squeezed or held a little longer - select.
  * "wink_left"   only the left eye - left click.
  * "wink_right"  only the right eye - right click.

Winks are told apart from blinks by which eye closed; hard blinks from natural
ones by duration and squeeze. Both vary a lot between people, so every
threshold lives in GestureConfig.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GestureConfig:
    closed: float = 0.50         # eyeBlink score at or above this = closed
    asymmetry: float = 0.25      # a wink's closed eye must exceed the other by this
    wink_min: float = 0.12       # seconds
    wink_max: float = 1.20
    blink_max: float = 2.50      # longer both-eye closures are rest, not a gesture
    hard_min: float = 0.40       # natural blinks are ~0.1-0.3s
    hard_squint: float = 0.85    # or a squeeze this strong (some people rest near .6)
    one_eye_share: float = 0.30  # both eyes closed on fewer frames than this = one-eyed
    one_eye_gap: float = 0.05    # ...and the closed side must lead by at least this
    refractory: float = 0.25     # ignore closures this soon after a gesture


class GestureDetector:
    def __init__(self, config: GestureConfig | None = None):
        self.config = config or GestureConfig()
        # Debug bookkeeping lives outside reset(): resetting them after
        # calibration once crashed the camera thread that logs them.
        self.closures = 0            # finished closures, for the debug log
        self.last_closure = None     # (duration, both share, mean L-R, squint, gesture)
        self.reset()

    def reset(self):
        self.start = None            # time the current closure began
        self.both = self.frames = 0
        self.diff = self.squint = 0.0
        self.last_gesture_at = -1e9

    @property
    def closing(self) -> bool:
        return self.start is not None

    def feed(self, t: float, left: float | None, right: float | None,
             squint: float = 0.0) -> str | None:
        """left/right: eyeBlink scores (0 open .. 1 closed); None = no face."""
        c = self.config
        if left is None or right is None:
            self.start = None        # lost the face mid-gesture: drop it
            return None
        left_closed, right_closed = left >= c.closed, right >= c.closed
        if left_closed or right_closed:
            if self.start is None:
                if t - self.last_gesture_at < c.refractory:
                    return None
                self.start = t
                self.both = self.frames = 0
                self.diff = self.squint = 0.0
            self.frames += 1
            self.both += left_closed and right_closed
            self.diff += left - right
            self.squint = max(self.squint, squint)
            return None
        if self.start is None:
            return None
        duration = t - self.start
        self.start = None
        gesture = self._classify(duration)
        n = max(1, self.frames)
        self.closures += 1
        self.last_closure = (duration, self.both / n, self.diff / n, self.squint, gesture)
        if gesture:
            self.last_gesture_at = t
        return gesture

    def _classify(self, duration: float) -> str | None:
        c = self.config
        n = max(1, self.frames)
        diff = self.diff / n
        # A wink usually half-closes the other eye too (the face muscles are
        # coupled), so judge by the average gap between the eyes, not by
        # whether the other eye stayed under the closed threshold.
        # Only one eye ever crossed the threshold: that is a wink, even when
        # the gap between the eyes is small on average.
        one_eyed = self.both / n < c.one_eye_share and abs(diff) >= c.one_eye_gap
        if abs(diff) >= c.asymmetry or one_eyed:
            if not c.wink_min <= duration <= c.wink_max:
                return None
            return "wink_left" if diff > 0 else "wink_right"
        if self.both / n >= 0.5:
            if duration > c.blink_max:
                return None
            if duration >= c.hard_min or self.squint >= c.hard_squint:
                return "hard_blink"
            return "blink"
        return None
