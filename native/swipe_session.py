"""Word-by-word swipe recording with blink boundaries (port of Gaize keyboard.js).

Each blink ends the current word and starts the next. We do not know how long
the eyes take to reach the next word's first letter after a blink, so each word
is decoded from several start offsets and the candidates are merged.
"""

from __future__ import annotations

import math

# Seconds after the boundary: ~p5/p25/p50/p75/p90 of 47 measured inter-word gaps.
OFFSETS = (0.150, 0.200, 0.275, 0.350, 0.450)
START_DELAY = 0.300


class SwipeSession:
    def __init__(self, decoder, offsets=OFFSETS, per_offset=3, radius=1.5,
                 temperature=0.5, start_delay=START_DELAY):
        self.decoder = decoder
        self.offsets = offsets
        self.per_offset = per_offset
        self.radius = radius
        self.temperature = temperature
        self.start_delay = start_delay
        self.slots = []          # one [{word, p}] list per word, best first
        self.path = None         # [(x, y, t)] while recording
        self.t0 = 0.0
        self.last = None

    @property
    def recording(self):
        return self.path is not None

    def feed(self, x, y, t):
        self.last = (x, y, t)
        if self.path is not None and t >= self.t0 + self.start_delay:
            self.path.append(self.last)
            return True
        return False

    def start(self, t):
        self.t0 = t
        # Eye position commonly drops during the blink that starts a word.
        # Begin with an empty path so that position cannot leak into decoding.
        self.path = []

    def end(self):
        """Close the current word. Returns its candidates (maybe empty)."""
        path, self.path = self.path, None
        if not path:
            return []
        results = []
        for offset in self.offsets:
            i = next((k for k, p in enumerate(path) if p[2] >= self.t0 + offset), None)
            if i is None:
                continue
            sub = [(x, y) for x, y, _ in path[max(0, i - 1):]]
            results += self.decoder.decode_scored(sub, limit=self.per_offset,
                                                  radius=self.radius)
        candidates = self._merge(results)
        if candidates:
            self.slots.append(candidates)
        return candidates

    def boundary(self, t):
        if self.path is not None:
            self.end()
        self.start(t)

    def delete_word(self):
        if self.slots:
            self.slots.pop()

    def clear(self):
        self.path = None
        self.slots = []

    def _merge(self, results):
        best = {}
        for cost, word in results:
            if word not in best or cost < best[word]:
                best[word] = cost
        ranked = sorted(best.items(), key=lambda item: item[1])
        if not ranked:
            return []
        exps = [math.exp(-(cost - ranked[0][1]) / self.temperature) for _, cost in ranked]
        total = sum(exps)
        return [{"word": word, "p": e / total} for (word, _), e in zip(ranked, exps)]
