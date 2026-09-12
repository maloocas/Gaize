"""Offline constrained sentence generation.

Why this exists
---------------
Measured on this machine: small local models (llama3.2:3b, qwen3.5:4b) satisfy
the initial-letter constraint only 5-8% of the time, because a character-level
constraint cuts across tokenisation. A large cloud model does far better (~98%
for gemini-2.5-flash) but needs the venue network to behave.

So the constraint is enforced *structurally* here instead of being requested
politely from a model. Two mechanisms, both offline and instant:

  1. exact-initials lookup over a corpus of real AAC-style utterances, and
  2. bigram-scored beam search over a letter-bucketed lexicon, which is valid
     by construction - every word is drawn from the bucket for its letter.

The result is a generator that cannot return an invalid candidate and cannot be
taken offline by bad wifi. It is the floor under the whole demo (doc s11).
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache

from .config import ROOT

_WORD = re.compile(r"[a-z']+")

CORPUS_PATH = ROOT / "data" / "corpus.txt"


def _tokenise(sentence: str) -> list[str]:
    return _WORD.findall(sentence.lower().replace("’", "'"))


@dataclass
class LanguageModel:
    unigram: Counter
    bigram: dict[str, Counter]
    starts: Counter
    buckets: dict[str, list[str]]
    sentences: list[str]
    total: int

    def log_p_start(self, word: str) -> float:
        return math.log((self.starts.get(word, 0) + 0.5) / (sum(self.starts.values()) + 0.5 * 500))

    def log_p_next(self, prev: str, word: str) -> float:
        """Bigram with interpolated backoff to unigram - sparse data needs it."""
        uni = (self.unigram.get(word, 0) + 0.5) / (self.total + 0.5 * len(self.unigram))
        row = self.bigram.get(prev)
        if not row:
            return math.log(uni)
        bi = row.get(word, 0) / sum(row.values())
        return math.log(0.75 * bi + 0.25 * uni)


@lru_cache(maxsize=1)
def load_model() -> LanguageModel:
    unigram: Counter = Counter()
    bigram: dict[str, Counter] = defaultdict(Counter)
    starts: Counter = Counter()
    sentences: list[str] = []

    if CORPUS_PATH.exists():
        for line in CORPUS_PATH.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            words = _tokenise(line)
            if not words:
                continue
            sentences.append(line)
            starts[words[0]] += 1
            unigram.update(words)
            for a, b in zip(words, words[1:]):
                bigram[a][b] += 1

    buckets: dict[str, list[str]] = defaultdict(list)
    for word, _count in unigram.most_common():
        if word and word[0].isalpha():
            buckets[word[0]].append(word)

    return LanguageModel(
        unigram=unigram,
        bigram=dict(bigram),
        starts=starts,
        buckets=dict(buckets),
        sentences=sentences,
        total=max(sum(unigram.values()), 1),
    )


def corpus_matches(tokens: list[str], limit: int = 6) -> list[str]:
    """Real corpus utterances whose word-initials match the input exactly."""
    from .expander import verify  # local import avoids a circular import at module load

    out: list[str] = []
    for sentence in load_model().sentences:
        if verify(sentence, tokens)[2]:
            out.append(sentence)
            if len(out) >= limit:
                break
    return out


def _candidates_for(token: str, lm: LanguageModel, extra: dict[str, list[str]],
                    width: int) -> list[str]:
    if len(token) > 1:
        return [token.lower()]
    letter = token.lower()
    pool = list(extra.get(letter, []))
    pool += [w for w in lm.buckets.get(letter, [])[:width] if w not in pool]
    return pool or [letter]


def generate(
    tokens: list[str],
    profile: dict | None = None,
    n: int = 6,
    beam_width: int = 80,
    lexicon_width: int = 45,
) -> list[str]:
    """Beam search for the most fluent word sequences fitting the constraint."""
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    lm = load_model()

    # Personal vocabulary gets its own bucket entries so names and the user's own
    # words are reachable even when the corpus never saw them.
    extra: dict[str, list[str]] = defaultdict(list)
    personal: set[str] = set()
    for key in ("people", "topics", "phrases"):
        for item in (profile or {}).get(key) or []:
            for word in _tokenise(str(item)):
                if word and word[0] not in extra or word not in extra[word[0]]:
                    extra[word[0]].append(word)
                personal.add(word)

    beams: list[tuple[float, list[str]]] = [(0.0, [])]
    for index, token in enumerate(tokens):
        options = _candidates_for(token, lm, extra, lexicon_width)
        nxt: list[tuple[float, list[str]]] = []
        for score, words in beams:
            for word in options:
                if index == 0:
                    step = lm.log_p_start(word)
                else:
                    step = lm.log_p_next(words[-1], word)
                if word in personal:
                    step += 0.35          # nudge toward the user's own vocabulary
                if words and word == words[-1]:
                    step -= 4.0           # block "I I", "the the"
                nxt.append((score + step, words + [word]))
        nxt.sort(key=lambda item: -item[0])
        beams = nxt[:beam_width]

    out: list[str] = []
    seen: set[str] = set()
    for _score, words in beams:
        sentence = " ".join(words)
        if sentence in seen:
            continue
        seen.add(sentence)
        out.append(sentence[0].upper() + sentence[1:])
        if len(out) >= n:
            break
    return out
