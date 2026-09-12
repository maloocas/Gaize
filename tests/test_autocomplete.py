"""Word suggestions for the on-screen keyboard.

Every selection costs an AAC user real time, so a suggestion that saves four
keypresses is worth more here than in an ordinary text field - and a suggestion
that destroys an already-finished word is worse than none at all.
"""
from pathlib import Path

import pytest

from native.autocomplete import Autocomplete

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def ac():
    return Autocomplete(ROOT / "native" / "swipe_words.txt",
                        ROOT / "data" / "corpus.txt",
                        ROOT / "data" / "profile.json")


class TestPrefixCompletion:
    def test_completes_a_partial_word(self, ac):
        assert "water" in ac.complete("wat")

    def test_never_offers_the_prefix_itself(self, ac):
        assert "help" not in ac.complete("help")

    def test_empty_prefix_offers_nothing(self, ac):
        assert ac.complete("") == []

    def test_unknown_prefix_degrades_quietly(self, ac):
        assert ac.complete("zzzqqx") == []

    def test_ranking_is_not_truncated_alphabetically(self, ac):
        # A scan cap once stopped at "maryland" and so never reached "maya",
        # the one name in the user's own profile.
        assert "maya" in ac.complete("m", limit=5)


class TestPriority:
    def test_a_name_outranks_common_english(self, ac):
        assert ac._score("maya") > ac._score("many")

    def test_a_name_outranks_another_personal_word(self, ac):
        assert ac._score("maya") > ac._score("mariners")

    def test_device_vocabulary_outranks_generic_english(self, ac):
        assert ac._score("hurts") > ac._score("hubbard")

    def test_articles_inside_profile_entries_are_not_names(self, ac):
        # "the nurse" must not make "the" rank as a person's name.
        assert "the" not in ac.people


class TestContext:
    def test_completion_follows_the_sentence(self, ac):
        # Prefix frequency alone offered "he", "have", "has" here.
        assert ac.suggest("my back h")[0] == "hurts"

    def test_next_word_after_a_space(self, ac):
        assert "water" in ac.suggest("i need some ")

    def test_cold_start_offers_somewhere_to_begin(self, ac):
        assert ac.suggest("") and ac.suggest("")[0] == "i"

    def test_suggestions_are_capped(self, ac):
        assert len(ac.suggest("a", limit=3)) <= 3

    def test_no_duplicates(self, ac):
        out = ac.suggest("can you t")
        assert len(out) == len(set(out))


class TestRobustness:
    def test_missing_files_do_not_raise(self, tmp_path):
        empty = Autocomplete(tmp_path / "nope.txt", tmp_path / "nope2.txt",
                             tmp_path / "nope3.json")
        assert empty.suggest("hello") == []
        assert empty.suggest("") == Autocomplete.__init__.__globals__["COLD_START"][:5]

    def test_malformed_profile_does_not_raise(self, tmp_path):
        bad = tmp_path / "profile.json"
        bad.write_text("{not json")
        Autocomplete(ROOT / "native" / "swipe_words.txt", None, bad)
