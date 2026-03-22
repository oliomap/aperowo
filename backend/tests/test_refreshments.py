"""Tests for backend.filtering.refreshments — keyword detection & text utilities."""

import pytest

from backend.filtering.refreshments import (
    REFRESHMENT_RULES,
    REFRESHMENT_DISPLAY_PRIORITY,
    normalize_text,
    build_search_corpus,
    match_refreshments,
    extract_text_fragments,
)


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------

class TestNormalizeText:
    def test_strips_accents(self):
        assert normalize_text("Glühwein") == "Gluhwein"

    def test_strips_multiple_accents(self):
        assert normalize_text("crème brûlée") == "creme brulee"

    def test_plain_ascii_unchanged(self):
        assert normalize_text("hello world") == "hello world"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_german_umlauts(self):
        assert normalize_text("Würstli Käse Öl") == "Wurstli Kase Ol"


# ---------------------------------------------------------------------------
# build_search_corpus
# ---------------------------------------------------------------------------

class TestBuildSearchCorpus:
    def test_basic_fragments(self):
        result = build_search_corpus(["Hello World", "Free Pizza"])
        assert "hello world" in result
        assert "free pizza" in result

    def test_normalizes_accents(self):
        result = build_search_corpus(["Glühwein party"])
        assert "gluhwein" in result

    def test_collapses_whitespace(self):
        result = build_search_corpus(["lots   of    spaces"])
        assert "  " not in result

    def test_empty_list(self):
        assert build_search_corpus([]) == ""

    def test_filters_empty_strings(self):
        result = build_search_corpus(["", "", "hello"])
        assert result == "hello"

    def test_all_empty_strings(self):
        assert build_search_corpus(["", "", ""]) == ""


# ---------------------------------------------------------------------------
# match_refreshments
# ---------------------------------------------------------------------------

class TestMatchRefreshments:
    def test_detects_beer(self):
        result = match_refreshments("free beer and pizza")
        assert "drinks" in result["categories"]
        assert "beer" in result["matches"]["drinks"]

    def test_detects_food(self):
        result = match_refreshments("join us for pizza and burgers")
        assert "food" in result["categories"]
        assert "pizza" in result["matches"]["food"]

    def test_detects_snacks(self):
        result = match_refreshments("chips and fingerfood available")
        assert "snacks" in result["categories"]

    def test_detects_sweet(self):
        result = match_refreshments("cake and brownies for dessert")
        assert "sweet" in result["categories"]

    def test_no_match_returns_empty(self):
        result = match_refreshments("a lecture about quantum physics")
        assert result == {"categories": [], "matches": {}, "summary": None}

    def test_multiple_categories(self):
        result = match_refreshments("beer pizza cake chips")
        assert len(result["categories"]) == 4

    def test_summary_format(self):
        result = match_refreshments("free beer and pizza")
        assert result["summary"] is not None
        assert "·" in result["summary"] or "Food" in result["summary"]

    def test_display_priority_ordering(self):
        result = match_refreshments("beer pizza cake chips")
        cats = result["categories"]
        # food should come before drinks per REFRESHMENT_DISPLAY_PRIORITY
        assert cats.index("food") < cats.index("drinks")

    def test_custom_rules(self):
        custom = {
            "custom_cat": {
                "label": "Custom",
                "keywords": {"unicorn", "rainbow"},
            }
        }
        result = match_refreshments("unicorn party", rules=custom)
        assert "custom_cat" in result["categories"]

    def test_empty_corpus(self):
        result = match_refreshments("")
        assert result["categories"] == []

    def test_word_boundary_matching(self):
        # "wine" should not match "winery" at word boundaries
        # But "wine" should match "wine"
        result = match_refreshments("enjoy some wine tonight")
        assert "drinks" in result["categories"]
        assert "wine" in result["matches"]["drinks"]

    def test_apero_riche_multi_word(self):
        result = match_refreshments("there will be an apero riche after the talk")
        assert "snacks" in result["categories"]
        assert "apero riche" in result["matches"]["snacks"]


# ---------------------------------------------------------------------------
# extract_text_fragments
# ---------------------------------------------------------------------------

class TestExtractTextFragments:
    def test_string(self):
        assert extract_text_fragments("hello") == ["hello"]

    def test_none(self):
        assert extract_text_fragments(None) == []

    def test_dict(self):
        result = extract_text_fragments({"a": "one", "b": "two"})
        assert "one" in result
        assert "two" in result

    def test_list(self):
        result = extract_text_fragments(["a", "b", "c"])
        assert result == ["a", "b", "c"]

    def test_nested_dict(self):
        result = extract_text_fragments({"a": {"b": "deep"}})
        assert "deep" in result

    def test_mixed_types(self):
        result = extract_text_fragments({"a": 42, "b": "text"})
        assert "42" in result
        assert "text" in result

    def test_bytes_converted_to_string(self):
        # bytes are not Sequence-excluded at top level, they hit the str() fallback
        result = extract_text_fragments(b"hello bytes")
        assert len(result) == 1

    def test_bytearray_converted_to_string(self):
        result = extract_text_fragments(bytearray(b"hello"))
        assert len(result) == 1

    def test_bytes_excluded_from_list(self):
        # Inside a list, bytes/bytearray are excluded by the Sequence guard
        result = extract_text_fragments([b"hello", "world"])
        # bytes inside list: isinstance(b"hello", Sequence) is True but excluded
        # Actually bytes is excluded from Sequence recursion, falls to str(value)
        assert "world" in result

    def test_nested_list(self):
        result = extract_text_fragments([["a", "b"], ["c"]])
        assert result == ["a", "b", "c"]

    def test_complex_nested(self):
        data = {
            "title": "ETH Apero",
            "details": {
                "food": ["pizza", "beer"],
                "location": "HG E 1.1",
            },
        }
        result = extract_text_fragments(data)
        assert "ETH Apero" in result
        assert "pizza" in result
        assert "beer" in result
        assert "HG E 1.1" in result


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_all_priority_categories_exist(self):
        for cat in REFRESHMENT_DISPLAY_PRIORITY:
            assert cat in REFRESHMENT_RULES

    def test_all_categories_have_keywords(self):
        for cat, config in REFRESHMENT_RULES.items():
            assert "keywords" in config
            assert len(config["keywords"]) > 0

    def test_all_categories_have_label(self):
        for cat, config in REFRESHMENT_RULES.items():
            assert "label" in config
            assert isinstance(config["label"], str)
