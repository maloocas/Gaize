"""Word suggestions for the on-screen keyboard.

Every selection costs an AAC user real time, so the point of this is to let a
word be finished in one press rather than five. Two kinds of suggestion:

  * prefix completion while a word is being typed, ranked by how common the
    word actually is, and
  * next-word prediction once a word is finished, from bigrams over the AAC
    corpus - the phrases this user's device is actually likely to say.

Both sources already ship with the project: swipe_words.txt carries 50k words
with real frequency counts, and data/corpus.txt is the conversational corpus
behind the offline sentence generator. Personal vocabulary from profile.json is
boosted above both, because names are exactly what a generic frequency list is
worst at and what a person most needs.

Entirely local and in-memory: this runs on every keystroke and cannot afford a
network round trip.
"""
from __future__ import annotations

import bisect
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

_WORD = re.compile(r"[a-z']+")

# Sensible openers when there is nothing to go on yet.
COLD_START = ["i", "can", "please", "you", "no", "yes", "thank", "help"]

# Articles and titles that appear inside profile entries such as "the nurse" or
# "Dr. Okafor". They are not names and must not inherit a name's priority.
NOT_A_NAME = {"the", "a", "an", "my", "mr", "mrs", "ms", "dr", "doctor", "nurse"}


class Autocomplete:
    def __init__(self, word_file: Path, corpus_file: Path | None = None,
                 profile_file: Path | None = None):
        self.frequency: dict[str, int] = {}
        self.sorted_words: list[str] = []
        self.bigrams: dict[str, Counter] = defaultdict(Counter)
        self.personal: set[str] = set()
        self.people: set[str] = set()
        self.corpus_words: set[str] = set()
        self._load_words(word_file)
        if corpus_file is not None:
            self._load_corpus(corpus_file)
        if profile_file is not None:
            self._load_profile(profile_file)

    # ---------------------------------------------------------------- loading
    def _load_words(self, path: Path) -> None:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            return
        for line in text.splitlines():
            parts = line.lower().split()
            if not parts or not parts[0].isalpha():
                continue
            word = parts[0]
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            if count > self.frequency.get(word, 0):
                self.frequency[word] = count
        self.sorted_words = sorted(self.frequency)

    def _load_corpus(self, path: Path) -> None:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            return
        for line in text.splitlines():
            words = _WORD.findall(line.lower())
            for first, second in zip(words, words[1:]):
                self.bigrams[first][second] += 1
            # Corpus words are far more representative of what this device says
            # than a generic web frequency list, so make sure they are reachable
            # by prefix even when the big list has never seen them.
            for word in words:
                self.corpus_words.add(word)
                if word not in self.frequency:
                    self.frequency[word] = 1
        self.sorted_words = sorted(self.frequency)

    def _load_profile(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for key in ("people", "topics", "phrases"):
            for item in data.get(key) or []:
                for word in _WORD.findall(str(item).lower()):
                    self.personal.add(word)
                    if key == "people" and word not in NOT_A_NAME:
                        self.people.add(word)
                    self.frequency.setdefault(word, 1)
        self.sorted_words = sorted(self.frequency)

    # ------------------------------------------------------------- suggesting
    def _score(self, word: str):
        """Rank in tiers, not by one blended number.

        A flat bonus does not work here: web frequencies span several orders of
        magnitude, so log-frequency alone put "man", "make" and "many" ahead of
        "Maya" when completing "m" for someone whose profile names Maya. Tiers
        make the intent explicit - the user's own vocabulary first, then words
        this device actually says, then general English - with frequency only
        breaking ties inside a tier.
        """
        if word in self.people:
            tier = 3
        elif word in self.personal:
            tier = 2
        elif word in self.corpus_words:
            tier = 1
        else:
            tier = 0
        return (tier, math.log(self.frequency.get(word, 1) + 1))

    def complete(self, prefix: str, limit: int = 5) -> list[str]:
        """Words starting with prefix, most likely first."""
        prefix = prefix.lower().strip()
        if not prefix:
            return []
        start = bisect.bisect_left(self.sorted_words, prefix)
        matches = []
        for word in self.sorted_words[start:]:
            if not word.startswith(prefix):
                break
            if word != prefix:
                matches.append(word)
        matches.sort(key=self._score, reverse=True)
        return matches[:limit]

    def next_word(self, previous: str, limit: int = 5) -> list[str]:
        """Likely words to follow the one just finished."""
        row = self.bigrams.get(previous.lower())
        if not row:
            return []
        ranked = sorted(row.items(),
                        key=lambda kv: (kv[1],) + self._score(kv[0]), reverse=True)
        return [word for word, _count in ranked[:limit]]

    def complete_in_context(self, previous: str, prefix: str,
                            limit: int = 5) -> list[str]:
        """Prefix matches that actually follow the previous word.

        Prefix frequency alone is context-blind: completing "my back h" it
        offered "he", "have" and "has" while the corpus plainly contains "My
        back hurts". Filtering the previous word's continuations by the prefix
        puts the word the sentence is actually heading towards first.
        """
        row = self.bigrams.get(previous.lower())
        if not row or not prefix:
            return []
        matches = [(count, word) for word, count in row.items()
                   if word.startswith(prefix) and word != prefix]
        matches.sort(key=lambda cw: (cw[0],) + self._score(cw[1]), reverse=True)
        return [word for _count, word in matches[:limit]]

    def suggest(self, text: str, limit: int = 5) -> list[str]:
        """Suggestions for the current state of the keyboard buffer."""
        if not text or not text.strip():
            return COLD_START[:limit]
        words = _WORD.findall(text.lower())
        if text.endswith(" "):
            following = self.next_word(words[-1], limit) if words else []
            if following:
                return following
            return [w for w in COLD_START if not words or w != words[-1]][:limit]
        if not words:
            return []
        partial = words[-1]
        previous = words[-2] if len(words) > 1 else ""
        out: list[str] = []
        if previous:
            out.extend(self.complete_in_context(previous, partial, limit))
        for word in self.complete(partial, limit * 2):
            if word not in out:
                out.append(word)
            if len(out) >= limit:
                break
        return out[:limit]
