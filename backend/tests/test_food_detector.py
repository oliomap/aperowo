"""Tests for backend.filtering.food_detector — food detection orchestration."""

import pytest

from backend.filtering.food_detector import detect_food, _build_food_type


# ---------------------------------------------------------------------------
# detect_food
# ---------------------------------------------------------------------------

class TestDetectFood:
    def test_event_with_pizza(self):
        event = {"title": "ETH Apero", "description": "Free pizza and beer for everyone"}
        result = detect_food(event)
        assert result is not None
        assert "refreshments" in result
        assert "food_type" in result
        assert "refreshment_details" in result

    def test_event_no_food(self):
        event = {"title": "Math Lecture", "description": "Quantum computing seminar"}
        result = detect_food(event)
        assert result is None

    def test_empty_event(self):
        result = detect_food({})
        assert result is None

    def test_nested_food_detection(self):
        event = {
            "title": "Department Party",
            "details": {"catering": "beer and wine will be served"},
        }
        result = detect_food(event)
        assert result is not None
        assert "drinks" in result["refreshment_details"]["categories"]

    def test_food_type_string(self):
        event = {"description": "pizza and beer and cake"}
        result = detect_food(event)
        assert result is not None
        assert isinstance(result["food_type"], str)
        assert len(result["food_type"]) > 0

    def test_refreshments_summary(self):
        event = {"description": "we serve sushi and wine"}
        result = detect_food(event)
        assert result is not None
        assert result["refreshments"] is not None

    def test_german_text(self):
        event = {"description": "Es gibt Bratwurst und Bier"}
        result = detect_food(event)
        assert result is not None

    def test_only_numbers(self):
        event = {"data": 12345}
        result = detect_food(event)
        assert result is None


# ---------------------------------------------------------------------------
# _build_food_type
# ---------------------------------------------------------------------------

class TestBuildFoodType:
    def test_single_category(self):
        details = {
            "categories": ["food"],
            "matches": {"food": ["pizza", "burger", "sushi"]},
        }
        result = _build_food_type(details)
        # Takes top 2 keywords
        assert "Pizza" in result
        assert "Burger" in result

    def test_multiple_categories(self):
        details = {
            "categories": ["food", "drinks"],
            "matches": {"food": ["pizza"], "drinks": ["beer", "wine"]},
        }
        result = _build_food_type(details)
        assert "Pizza" in result
        assert "Beer" in result

    def test_empty_categories(self):
        details = {"categories": [], "matches": {}}
        result = _build_food_type(details)
        assert result == "Food & Drinks"

    def test_missing_matches(self):
        details = {"categories": ["food"], "matches": {}}
        result = _build_food_type(details)
        assert result == "Food & Drinks"
