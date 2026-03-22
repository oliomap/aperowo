"""Tests for backend.filtering.validators — event quality validation."""

import pytest

from backend.filtering.validators import is_valid_event


class TestGarbageLocations:
    def test_rejects_button(self):
        event = {"location": "button", "title": "Test"}
        valid, reason = is_valid_event(event)
        assert not valid
        assert "garbage location" in reason

    def test_rejects_undefined(self):
        event = {"location": "undefined", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert not valid

    def test_rejects_null(self):
        event = {"location": "null", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert not valid

    def test_rejects_none_string(self):
        event = {"location": "none", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert not valid

    def test_rejects_na(self):
        event = {"location": "N/A", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert not valid

    def test_accepts_real_location(self):
        event = {"location": "HG E 1.1", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert valid


class TestPriceAsLocation:
    def test_rejects_chf_price(self):
        event = {"location": "CHF 15.00", "title": "Test"}
        valid, reason = is_valid_event(event)
        assert not valid
        assert "price as location" in reason

    def test_accepts_non_price(self):
        event = {"location": "Room 101", "title": "Test"}
        valid, _ = is_valid_event(event)
        assert valid


class TestHtmlFragments:
    def test_rejects_html_location(self):
        event = {"location": "page.html", "title": "Test"}
        valid, reason = is_valid_event(event)
        assert not valid
        assert "HTML fragment" in reason


class TestTemplateTitles:
    def test_rejects_event_detail_title(self):
        event = {"title": "Event Detail —", "location": ""}
        valid, reason = is_valid_event(event)
        assert not valid
        assert "page template" in reason

    def test_rejects_news_events_title(self):
        event = {"title": "News & Events — Something", "location": ""}
        valid, reason = is_valid_event(event)
        assert not valid

    def test_rejects_homepage_title(self):
        event = {"title": "Homepage - ETH", "location": ""}
        valid, reason = is_valid_event(event)
        assert not valid

    def test_accepts_normal_title(self):
        event = {"title": "ETH Pizza Night", "location": ""}
        valid, _ = is_valid_event(event)
        assert valid


class TestStaleDates:
    def test_rejects_old_date(self):
        event = {"date": "2024-06-15", "title": "Old Event", "location": ""}
        valid, reason = is_valid_event(event)
        assert not valid
        assert "stale date" in reason

    def test_accepts_recent_date(self):
        event = {"date": "2026-03-22", "title": "New Event", "location": ""}
        valid, _ = is_valid_event(event)
        assert valid

    def test_accepts_no_date(self):
        event = {"title": "Event", "location": ""}
        valid, _ = is_valid_event(event)
        assert valid


class TestInvalidTimeRanges:
    def test_rejects_end_before_start(self):
        event = {
            "title": "Event",
            "location": "",
            "start_time": "18:00",
            "end_time": "14:00",
        }
        valid, reason = is_valid_event(event)
        assert not valid
        assert "invalid time range" in reason

    def test_accepts_midnight_crossover(self):
        event = {
            "title": "Event",
            "location": "",
            "start_time": "22:00",
            "end_time": "02:00",
        }
        valid, _ = is_valid_event(event)
        assert valid

    def test_accepts_normal_range(self):
        event = {
            "title": "Event",
            "location": "",
            "start_time": "14:00",
            "end_time": "18:00",
        }
        valid, _ = is_valid_event(event)
        assert valid

    def test_accepts_missing_times(self):
        event = {"title": "Event", "location": ""}
        valid, _ = is_valid_event(event)
        assert valid


class TestEdgeCases:
    def test_completely_empty_event(self):
        valid, _ = is_valid_event({})
        assert valid

    def test_none_location(self):
        event = {"location": None, "title": "Test"}
        valid, _ = is_valid_event(event)
        assert valid
