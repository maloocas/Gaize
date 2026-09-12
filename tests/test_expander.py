"""Tests for the parts that must not silently break: constraint verification,
parsing of messy model output, and the offline generator's guarantees."""
from __future__ import annotations

import asyncio

import pytest

from server.constrained import generate as constrained_generate
from server.expander import (
    expand,
    initials_of,
    normalise_word,
    parse_lines,
    phrasebank_hits,
    score,
    split_sentence,
    verify,
    Candidate,
)

PROFILE = {
    "people": ["Maya"],
    "topics": ["back pain"],
    "phrases": ["I want to go home", "My back hurts a lot"],
}


class TestVerify:
    def test_exact_match(self):
        assert verify("I want to go home", ["i", "w", "t", "g", "h"]) == (5, 5, True)

    def test_case_and_punctuation_ignored(self):
        assert verify("I'm tired, really.", ["i", "t", "r"])[2] is True

    def test_too_many_words_is_not_exact(self):
        matched, total, exact = verify("I want to go home now", ["i", "w", "t", "g", "h"])
        assert exact is False
        assert (matched, total) == (5, 5)

    def test_too_few_words_is_not_exact(self):
        assert verify("I want", ["i", "w", "t"])[2] is False

    def test_wrong_initial_counted(self):
        matched, total, exact = verify("I need to go home", ["i", "w", "t", "g", "h"])
        assert (matched, total, exact) == (4, 5, False)

    def test_whole_word_token(self):
        assert verify("Please call Maya", ["p", "c", "Maya"])[2] is True

    def test_whole_word_token_mismatch(self):
        assert verify("Please call Ruth", ["p", "c", "Maya"])[2] is False

    def test_empty_tokens(self):
        assert verify("anything", []) == (0, 0, False)

    def test_accents_normalised(self):
        assert normalise_word("café") == "cafe"

    def test_initials_helper(self):
        assert initials_of("My back hurts a lot") == "mbhal"

    def test_hyphen_kept_as_one_word(self):
        assert split_sentence("well-rested today") == ["well-rested", "today"]


class TestParseLines:
    def test_strips_numbering_and_bullets(self):
        raw = "1. I am tired\n- I am thirsty\n* I am there"
        assert parse_lines(raw) == ["I am tired", "I am thirsty", "I am there"]

    def test_drops_preamble_and_dedupes(self):
        raw = "Here are 3 sentences:\nI am tired\nI am tired\nNote: done"
        assert parse_lines(raw) == ["I am tired"]

    def test_strips_quotes(self):
        assert parse_lines('"I am tired"') == ["I am tired"]

    def test_ignores_overlong_lines(self):
        assert parse_lines("x" * 300) == []


class TestPhraseBank:
    def test_exact_initials_hit(self):
        hits = phrasebank_hits(["i", "w", "t", "g", "h"], PROFILE)
        assert [h.text for h in hits] == ["I want to go home"]

    def test_no_false_positive(self):
        assert phrasebank_hits(["z", "z", "z"], PROFILE) == []


class TestScoring:
    def test_exact_outranks_partial(self):
        good = score(Candidate("I want to go home", 0, "llm", True, 5, 5),
                     ["i", "w", "t", "g", "h"], PROFILE, [])
        bad = score(Candidate("I need to go home", 0, "llm", False, 4, 5),
                    ["i", "w", "t", "g", "h"], PROFILE, [])
        assert good.score > bad.score

    def test_personal_vocabulary_boost(self):
        with_name = score(Candidate("Please call Maya", 0, "llm", True, 3, 3),
                          ["p", "c", "m"], PROFILE, [])
        without = score(Candidate("Please call mum", 0, "llm", True, 3, 3),
                        ["p", "c", "m"], PROFILE, [])
        assert with_name.score > without.score

    def test_context_overlap_boost(self):
        turns = ["Does your back still hurt?"]
        with_ctx = score(Candidate("My back hurts", 0, "llm", True, 3, 3),
                         ["m", "b", "h"], {}, turns)
        without = score(Candidate("My bed helps", 0, "llm", True, 3, 3),
                        ["m", "b", "h"], {}, turns)
        assert with_ctx.score > without.score

    def test_unsafe_word_demoted(self):
        clean = score(Candidate("I want to go home", 0, "llm", True, 5, 5),
                      ["i", "w", "t", "g", "h"], {}, [])
        flagged = score(Candidate("I want to get high", 0, "llm", True, 5, 5),
                        ["i", "w", "t", "g", "h"], {}, [])
        assert flagged.score < clean.score


class TestConstrainedGenerator:
    @pytest.mark.parametrize("tokens", [
        ["i", "a", "t"],
        ["i", "w", "t", "g", "h"],
        ["m", "b", "h", "a", "l"],
        ["c", "y", "t", "m", "p"],
        ["p", "c", "m"],
    ])
    def test_every_candidate_satisfies_constraint(self, tokens):
        out = constrained_generate(tokens, PROFILE, n=5)
        assert out, "generator must always return something"
        for sentence in out:
            assert verify(sentence, tokens)[2], f"{sentence!r} violates {tokens}"

    def test_empty_input(self):
        assert constrained_generate([], PROFILE) == []

    def test_respects_whole_word_tokens(self):
        out = constrained_generate(["p", "c", "maya"], PROFILE, n=3)
        assert all(s.lower().split()[-1] == "maya" for s in out)


class TestExpandOffline:
    """The offline path must work with no network and no model."""

    def test_never_empty_and_all_valid(self):
        tokens = ["i", "n", "s", "w"]
        result = asyncio.run(expand(tokens, [], PROFILE, provider_name="constrained"))
        assert result.candidates
        assert all(c.exact for c in result.candidates)
        assert result.calls == 0

    def test_empty_input_is_handled(self):
        result = asyncio.run(expand([], [], PROFILE, provider_name="constrained"))
        assert result.candidates == []

    def test_saved_phrase_ranks_first(self):
        result = asyncio.run(
            expand(["i", "w", "t", "g", "h"], [], PROFILE, provider_name="constrained"))
        assert result.candidates[0].text == "I want to go home"
