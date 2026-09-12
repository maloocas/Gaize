"""Turn very sparse, ambiguous switch input into ranked full sentences.

Input protocol
--------------
The user's selections arrive as a token list. Each token is either

  * a single letter - the *initial* of a word ("i w t g h"), or
  * a whole word    - picked from the word grid ("water", "nurse").

So ``["i", "w", "t", "g", "h"]`` means "a five-word sentence whose words start
with i, w, t, g, h" -> "I want to go home". This initialism protocol is what
makes the acceleration large: five switch selections instead of eighteen.

Why this is not a thin prompt wrapper
-------------------------------------
A raw LLM ignores the initial-letter constraint often enough to be unusable, so
generation is only step one of four:

  1. generate over-many candidates from a lean prompt,
  2. *hard-verify* each candidate against the token constraint,
  3. run one repair call if too few survived, quoting the actual violations,
  4. score and rank survivors (constraint fit, personal-vocabulary overlap,
     brevity, context overlap) and dedupe.

A zero-latency phrase-bank lookup runs before any of it, so the user's own
saved phrases appear instantly and the demo has a floor on responsiveness.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict

from .config import settings
from .constrained import corpus_matches, generate as constrained_generate
from .providers import get_provider

_WORD_SPLIT = re.compile(r"[^\w'’-]+")
_STRIP_EDGES = re.compile(r"^[^\w]+|[^\w]+$")


def normalise_word(word: str) -> str:
    """Lowercase, strip punctuation and accents so comparisons are stable."""
    word = _STRIP_EDGES.sub("", word)
    word = unicodedata.normalize("NFKD", word)
    word = "".join(ch for ch in word if not unicodedata.combining(ch))
    return word.lower()


def split_sentence(sentence: str) -> list[str]:
    return [w for w in (normalise_word(p) for p in _WORD_SPLIT.split(sentence)) if w]


def initials_of(sentence: str) -> str:
    return "".join(w[0] for w in split_sentence(sentence) if w)


@dataclass
class Candidate:
    text: str
    score: float
    source: str              # "phrasebank" | "llm" | "llm-repair" | "stub"
    exact: bool              # satisfies every token constraint
    matched: int = 0         # how many token constraints were satisfied
    total: int = 0
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def verify(sentence: str, tokens: list[str]) -> tuple[int, int, bool]:
    """Check a candidate against the token constraint.

    Returns (matched, total, exact). ``exact`` requires the word count to match
    the token count *and* every token to be satisfied - a candidate with extra
    words is not a valid expansion of the user's input, however nice it reads.
    """
    words = split_sentence(sentence)
    total = len(tokens)
    if total == 0:
        return 0, 0, False
    matched = 0
    for tok, word in zip(tokens, words):
        tok_n = normalise_word(tok)
        if not tok_n or not word:
            continue
        if len(tok_n) == 1:
            if word[0] == tok_n:
                matched += 1
        elif word == tok_n or word.startswith(tok_n):
            matched += 1
    exact = matched == total and len(words) == total
    return matched, total, exact


SYSTEM_PROMPT = (
    "You expand abbreviated input for someone using an assistive communication "
    "device. They select only the FIRST LETTER of each word, so you must "
    "reconstruct the sentence they most likely meant.\n"
    "Absolute rules:\n"
    "1. Output exactly one sentence per line, nothing else. No numbering, no "
    "quotes, no commentary, no blank lines.\n"
    "2. Each sentence must have EXACTLY as many words as there are letters, and "
    "word N must begin with letter N.\n"
    "3. Write in first person as the person speaking. Keep it natural, short and "
    "conversational - the kind of thing someone actually says out loud.\n"
    "4. Order your lines best guess first.\n\n"
    "Examples:\n"
    "Input: i a t\nI am tired\n\n"
    "Input: c y h m\nCan you help me\n\n"
    "Input: m b h a l\nMy back hurts a lot\n"
)


def _format_tokens(tokens: list[str]) -> str:
    parts = []
    for i, tok in enumerate(tokens, 1):
        if len(tok) == 1:
            parts.append(f"{i}. a word starting with '{tok.lower()}'")
        else:
            parts.append(f"{i}. the word '{tok}'")
    return "\n".join(parts)


def build_prompt(
    tokens: list[str],
    partner_turns: list[str],
    profile: dict,
    n: int,
) -> str:
    """Lean prompt: only the last few partner turns, only relevant profile bits."""
    lines: list[str] = []

    turns = [t for t in partner_turns if t.strip()][-settings.context_turns:]
    if turns:
        lines.append("Conversation so far (the other person is speaking to them):")
        lines.extend(f'  them: "{t.strip()}"' for t in turns)
        lines.append("")

    name = profile.get("name")
    about = profile.get("about")
    people = profile.get("people") or []
    topics = profile.get("topics") or []
    if name or about or people or topics:
        lines.append("About the person speaking:")
        if name:
            lines.append(f"  name: {name}")
        if about:
            lines.append(f"  notes: {about}")
        if people:
            lines.append(f"  people in their life: {', '.join(people[:12])}")
        if topics:
            lines.append(f"  current topics: {', '.join(topics[:12])}")
        lines.append("")

    letters = " ".join(t.lower() for t in tokens)
    lines.append(f"They selected {len(tokens)} items: {letters}")
    lines.append("Meaning:")
    lines.append(_format_tokens(tokens))
    lines.append("")
    lines.append(
        f"Give {n} different likely sentences, one per line, best first. "
        f"Every line must be exactly {len(tokens)} words long."
    )
    return "\n".join(lines)


def build_repair_prompt(
    tokens: list[str],
    rejected: list[str],
    n: int,
) -> str:
    letters = " ".join(t.lower() for t in tokens)
    lines = [
        f"Those were wrong. The input was {len(tokens)} items: {letters}",
        "Meaning:",
        _format_tokens(tokens),
        "",
        "Rejected attempts and why:",
    ]
    for text in rejected[:4]:
        words = split_sentence(text)
        lines.append(
            f'  "{text}" -> {len(words)} words ({initials_of(text)}), '
            f"needed {len(tokens)} words ({''.join(t[0].lower() for t in tokens)})"
        )
    lines.append("")
    lines.append(
        f"Try again. Output {n} sentences, one per line, each EXACTLY "
        f"{len(tokens)} words, word N starting with letter N. Nothing else."
    )
    return "\n".join(lines)


_LEADING_JUNK = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def parse_lines(raw: str) -> list[str]:
    """Pull sentence candidates out of a model response."""
    out: list[str] = []
    for line in raw.splitlines():
        line = _LEADING_JUNK.sub("", line.strip())
        line = line.strip().strip('"').strip("'").strip()
        if not line or len(line) > 240:
            continue
        # Drop the model talking about its own work rather than answering.
        if line.lower().startswith(("here are", "sure", "okay,", "note:", "sentence")):
            continue
        if line.endswith(":"):
            continue
        out.append(line)
    return list(dict.fromkeys(out))


def phrasebank_hits(tokens: list[str], profile: dict) -> list[Candidate]:
    """Zero-latency path: the user's own saved phrases, matched on initials."""
    hits: list[Candidate] = []
    for phrase in profile.get("phrases") or []:
        if not isinstance(phrase, str) or not phrase.strip():
            continue
        matched, total, exact = verify(phrase, tokens)
        if exact:
            hits.append(Candidate(
                text=phrase.strip(), score=2.0, source="phrasebank",
                exact=True, matched=matched, total=total,
                reasons=["saved phrase, exact match"],
            ))
    return hits


# Where a candidate came from, as a tie-breaker. The user's own saved phrases beat
# everything; a context-aware model beats a generic corpus utterance, which beats
# a beam-search construction.
# Small demotion list. A generator working from sparse letters will occasionally
# land on something crude or alarming that the user never meant; for an assistive
# device the cost of surfacing it is high and the cost of ranking it last is zero.
DEMOTE = {
    "high", "drunk", "stoned", "kill", "die", "damn", "hell", "hate",
    "stupid", "sex", "sexy", "drugs", "shit", "fuck", "crap", "suicide",
}


SOURCE_BONUS = {
    "phrasebank": 1.00,
    "llm": 0.25,
    "llm-repair": 0.20,
    "corpus": 0.15,
    "constrained": 0.0,
}


def score(
    cand: Candidate,
    tokens: list[str],
    profile: dict,
    partner_turns: list[str],
) -> Candidate:
    """Rank survivors. Constraint fit dominates; the rest are tie-breakers."""
    reasons = list(cand.reasons)
    base = 1.0 if cand.exact else 0.45 * (cand.matched / max(cand.total, 1))
    if cand.exact:
        reasons.append("satisfies every letter")
    else:
        reasons.append(f"partial fit {cand.matched}/{cand.total}")

    words = set(split_sentence(cand.text))

    vocab = set()
    for key in ("people", "topics"):
        for item in profile.get(key) or []:
            vocab.update(split_sentence(str(item)))
    for phrase in profile.get("phrases") or []:
        vocab.update(split_sentence(str(phrase)))
    overlap = words & vocab
    if overlap:
        base += min(0.05 * len(overlap), 0.20)
        reasons.append(f"personal vocabulary: {', '.join(sorted(overlap)[:3])}")

    ctx_words: set[str] = set()
    for turn in partner_turns[-settings.context_turns:]:
        ctx_words.update(split_sentence(turn))
    ctx_overlap = {w for w in words & ctx_words if len(w) > 3}
    if ctx_overlap:
        base += min(0.04 * len(ctx_overlap), 0.12)
        reasons.append(f"echoes what was just said: {', '.join(sorted(ctx_overlap)[:3])}")

    flagged = words & DEMOTE
    if flagged:
        base -= 0.9
        reasons.append(f"demoted: unlikely/unsafe word ({', '.join(sorted(flagged))})")

    # Mild brevity preference: spoken AAC output is short.
    base -= 0.004 * max(len(cand.text) - 30, 0)

    base += SOURCE_BONUS.get(cand.source, 0.0)

    cand.score = round(base, 4)
    cand.reasons = reasons
    return cand


@dataclass
class ExpansionResult:
    candidates: list[Candidate]
    provider: str
    model: str
    latency_ms: int
    calls: int
    degraded: bool             # true when we fell back to stub / relaxed matches
    note: str | None = None

    def as_dict(self) -> dict:
        return {
            "candidates": [c.as_dict() for c in self.candidates],
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "calls": self.calls,
            "degraded": self.degraded,
            "note": self.note,
        }


async def _llm_pass(
    provider_name: str,
    tokens: list[str],
    partner_turns: list[str],
    profile: dict,
    want: int,
) -> tuple[list[Candidate], list[Candidate], int, int, str | None]:
    """One provider's attempt: generate, verify, and repair once if needed."""
    provider = get_provider(provider_name)
    exact: list[Candidate] = []
    partial: list[Candidate] = []
    rejected: list[str] = []
    latency = 0
    calls = 0

    completion = await provider.complete(
        SYSTEM_PROMPT, build_prompt(tokens, partner_turns, profile, want * 2))
    latency += completion.latency_ms
    calls += 1
    if completion.error:
        return exact, partial, latency, calls, f"{provider.name}: {completion.error}"

    for text in parse_lines(completion.text):
        matched, total, is_exact = verify(text, tokens)
        cand = Candidate(text, 0.0, "llm", is_exact, matched, total)
        (exact if is_exact else partial).append(cand)
        if not is_exact:
            rejected.append(text)

    # Repair pass quotes the actual violations back at the model.
    if len(exact) < 2 and rejected:
        repair = await provider.complete(
            SYSTEM_PROMPT, build_repair_prompt(tokens, rejected, want * 2))
        latency += repair.latency_ms
        calls += 1
        if not repair.error:
            for text in parse_lines(repair.text):
                matched, total, is_exact = verify(text, tokens)
                cand = Candidate(text, 0.0, "llm-repair", is_exact, matched, total)
                (exact if is_exact else partial).append(cand)

    return exact, partial, latency, calls, None


async def expand(
    tokens: list[str],
    partner_turns: list[str] | None = None,
    profile: dict | None = None,
    provider_name: str | None = None,
    n: int | None = None,
) -> ExpansionResult:
    """Run the candidate ladder and return ranked, constraint-checked sentences.

    Ladder, cheapest and most certain first:
      1. the user's saved phrases (instant, exact-initials match),
      2. each configured LLM provider in turn, hard-verified,
      3. the offline constrained generator, which is always valid.
    Step 3 runs regardless, so the candidate list is never empty and never
    depends on the network.
    """
    tokens = [t for t in (tok.strip() for tok in tokens) if t]
    partner_turns = partner_turns or []
    profile = profile or {}
    want = n or settings.n_candidates

    if not tokens:
        return ExpansionResult([], "none", "none", 0, 0, False, "no input yet")

    pool: list[Candidate] = phrasebank_hits(tokens, profile)
    partial: list[Candidate] = []
    latency = 0
    calls = 0
    notes: list[str] = []
    used: list[str] = ["phrasebank"] if pool else []

    chain = [provider_name] if provider_name else settings.provider_chain
    for name in chain:
        if name == "constrained":
            continue
        exact, near, ms, n_calls, err = await _llm_pass(
            name, tokens, partner_turns, profile, want)
        latency += ms
        calls += n_calls
        if err:
            notes.append(err)
            continue
        partial.extend(near)
        if exact:
            pool.extend(exact)
            used.append(name)
            if len(pool) >= want:
                break

    # Offline floor: valid by construction, ~10ms, no network.
    needed = max(want - len(pool), 2)
    for text in corpus_matches(tokens, limit=needed):
        matched, total, is_exact = verify(text, tokens)
        pool.append(Candidate(text, 0.0, "corpus", is_exact, matched, total,
                              reasons=["real utterance from the offline corpus"]))
    for text in constrained_generate(tokens, profile, n=needed + 3):
        matched, total, is_exact = verify(text, tokens)
        pool.append(Candidate(text, 0.0, "constrained", is_exact, matched, total,
                              reasons=["built offline under the letter constraint"]))
    if not used:
        used.append("constrained")

    degraded = not any(c.source in ("llm", "llm-repair") for c in pool)

    # Only ever show near-misses if the whole ladder somehow came up short.
    if len(pool) < want:
        partial.sort(key=lambda c: -(c.matched / max(c.total, 1)))
        for cand in partial:
            if len(pool) >= want:
                break
            cand.reasons.append("near miss - letters do not all line up")
            pool.append(cand)

    ranked = [score(c, tokens, profile, partner_turns) for c in pool]
    seen: set[str] = set()
    unique: list[Candidate] = []
    for cand in sorted(ranked, key=lambda c: -c.score):
        key = " ".join(split_sentence(cand.text))
        if key in seen:
            continue
        seen.add(key)
        unique.append(cand)

    return ExpansionResult(
        candidates=unique[:want],
        provider="+".join(used) or "none",
        model=settings.openrouter_model if "openrouter" in used else (
            settings.ollama_model if "ollama" in used else "offline"),
        latency_ms=latency,
        calls=calls,
        degraded=degraded,
        note="; ".join(notes) or None,
    )
