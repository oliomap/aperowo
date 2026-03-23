"""Tests for backend.normalize — slugify, event IDs, fuzzy dedup."""

import pytest

from backend.normalize import slugify, make_event_id, is_duplicate

# Some tests require thefuzz for meaningful fuzzy matching
try:
    from thefuzz import fuzz as _fuzz
    _HAS_THEFUZZ = True
except ImportError:
    _HAS_THEFUZZ = False

needs_thefuzz = pytest.mark.skipif(
    not _HAS_THEFUZZ, reason="thefuzz not installed"
)


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        assert slugify("Pizza & Beer!") == "pizza-beer"

    def test_collapses_dashes(self):
        assert slugify("a---b") == "a-b"

    def test_strips_trailing_dashes(self):
        assert slugify("hello---") == "hello"

    def test_truncates_at_60(self):
        long_text = "a" * 100
        assert len(slugify(long_text)) <= 60

    def test_empty_string(self):
        assert slugify("") == ""

    def test_only_special_chars(self):
        assert slugify("!!!@@@###") == ""

    def test_whitespace_handling(self):
        assert slugify("  spaces  everywhere  ") == "spaces-everywhere"

    def test_unicode_stripped(self):
        # Non-ASCII chars like ü are removed by [^a-z0-9\s-]
        result = slugify("Glühwein Party")
        assert "glhwein" in result or "glwein" in result


# ---------------------------------------------------------------------------
# make_event_id
# ---------------------------------------------------------------------------

class TestMakeEventId:
    def test_basic(self):
        result = make_event_id("eth", "Pizza Night", "2026-03-22")
        assert result == "eth-pizza-night-2026-03-22"

    def test_empty_title(self):
        result = make_event_id("eth", "", "2026-03-22")
        assert result == "eth-event-2026-03-22"

    def test_no_date(self):
        result = make_event_id("eth", "Pizza Night", None)
        assert result == "eth-pizza-night-nodate"

    def test_empty_title_and_no_date(self):
        result = make_event_id("eth", "", None)
        assert result == "eth-event-nodate"

    def test_special_chars_in_title(self):
        result = make_event_id("src", "Beer & Pizza!", "2026-01-01")
        assert "src-" in result
        assert "2026-01-01" in result


# ---------------------------------------------------------------------------
# is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    def test_exact_match(self):
        seen = {"ETH Pizza Night"}
        assert is_duplicate("ETH Pizza Night", seen) is True

    @needs_thefuzz
    def test_fuzzy_match(self):
        seen = {"ETH Pizza Night 2026"}
        assert is_duplicate("ETH Pizza Night", seen) is True

    def test_no_match(self):
        seen = {"Quantum Physics Lecture"}
        assert is_duplicate("ETH Pizza Night", seen) is False

    def test_empty_title(self):
        seen = {"anything"}
        assert is_duplicate("", seen) is False

    def test_empty_seen_set(self):
        assert is_duplicate("ETH Pizza Night", set()) is False

    @needs_thefuzz
    def test_custom_threshold(self):
        seen = {"ETH Pizza Night 2026"}
        # partial_ratio("Pizza", "ETH Pizza Night 2026") == 100 since "Pizza" is a substring
        assert is_duplicate("Pizza", seen, threshold=100) is True
        # Completely different string should not match even at lower threshold
        assert is_duplicate("Quantum Mechanics", seen, threshold=95) is False

    @needs_thefuzz
    def test_similar_titles(self):
        seen = {"Apéro at ETH Main Building"}
        assert is_duplicate("Apero at ETH Main Building", seen) is True
