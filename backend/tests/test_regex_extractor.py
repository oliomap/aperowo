"""Tests for backend.extraction.regex_extractor — date/time/location parsing."""

import pytest

from backend.extraction.regex_extractor import (
    extract_date_from_text,
    extract_times_from_text,
    extract_location_from_text,
    extract_events_from_raw,
)


# ---------------------------------------------------------------------------
# extract_date_from_text
# ---------------------------------------------------------------------------

class TestExtractDate:
    def test_iso_format(self):
        assert extract_date_from_text("event on 2026-03-22") == "2026-03-22"

    def test_month_first(self):
        assert extract_date_from_text("March 22, 2026") == "2026-03-22"

    def test_day_first(self):
        # "22 March 2026" — the _DAY_FIRST_RE matches this
        result = extract_date_from_text("22 March 2026")
        assert result is not None
        assert result.startswith("2026-03")

    def test_euro_format_dot(self):
        assert extract_date_from_text("22.03.2026") == "2026-03-22"

    def test_euro_format_slash(self):
        assert extract_date_from_text("22/03/2026") == "2026-03-22"

    def test_abbreviated_month(self):
        assert extract_date_from_text("Mar 22, 2026") == "2026-03-22"

    def test_empty_string(self):
        assert extract_date_from_text("") is None

    def test_no_date(self):
        assert extract_date_from_text("just some random text") is None

    def test_invalid_date(self):
        assert extract_date_from_text("2026-13-45") is None

    def test_two_digit_year(self):
        assert extract_date_from_text("Mar 22, 26") == "2026-03-22"

    def test_ordinal_day(self):
        assert extract_date_from_text("March 22nd, 2026") == "2026-03-22"

    def test_month_with_period(self):
        assert extract_date_from_text("Mar. 22, 2026") == "2026-03-22"

    # --- Day-first edge cases ---

    def test_day_first_abbreviated_month(self):
        assert extract_date_from_text("22 Mar 2026") == "2026-03-22"

    def test_day_first_ordinal_st(self):
        assert extract_date_from_text("1st January 2026") == "2026-01-01"

    def test_day_first_ordinal_nd(self):
        assert extract_date_from_text("2nd February 2026") == "2026-02-02"

    def test_day_first_ordinal_rd(self):
        assert extract_date_from_text("3rd March 2026") == "2026-03-03"

    def test_day_first_ordinal_th(self):
        assert extract_date_from_text("15th June 2026") == "2026-06-15"

    def test_day_first_two_digit_year(self):
        assert extract_date_from_text("22 March 26") == "2026-03-22"

    def test_day_first_abbreviated_with_period(self):
        assert extract_date_from_text("22 Mar. 2026") == "2026-03-22"

    def test_day_first_sept_variant(self):
        assert extract_date_from_text("15 Sept 2026") == "2026-09-15"

    def test_day_first_sept_dot_variant(self):
        assert extract_date_from_text("15 Sept. 2026") == "2026-09-15"

    # --- Year coercion edge cases ---

    def test_two_digit_year_49_maps_to_2049(self):
        assert extract_date_from_text("Mar 22, 49") == "2049-03-22"

    def test_two_digit_year_50_maps_to_1950(self):
        assert extract_date_from_text("Mar 22, 50") == "1950-03-22"

    def test_two_digit_year_99_maps_to_1999(self):
        assert extract_date_from_text("Mar 22, 99") == "1999-03-22"

    def test_two_digit_year_00_maps_to_2000(self):
        assert extract_date_from_text("Mar 22, 00") == "2000-03-22"

    def test_euro_format_two_digit_year(self):
        assert extract_date_from_text("22.03.26") == "2026-03-22"

    def test_euro_format_two_digit_year_high(self):
        assert extract_date_from_text("22.03.99") == "1999-03-22"

    # --- Invalid / boundary dates ---

    def test_invalid_month_31_feb(self):
        assert extract_date_from_text("2026-02-30") is None

    def test_invalid_euro_date(self):
        assert extract_date_from_text("32.13.2026") is None

    def test_day_zero(self):
        """Day 0 is not a valid day."""
        assert extract_date_from_text("0 March 2026") is None

    def test_month_first_no_year(self):
        """Month-first without year returns None (year coercion fails)."""
        assert extract_date_from_text("March 22") is None

    def test_day_first_no_year(self):
        """Day-first without year returns None (year coercion fails)."""
        assert extract_date_from_text("22 March") is None

    # --- ISO takes priority ---

    def test_iso_preferred_over_others(self):
        """ISO format should be matched first even if other formats present."""
        text = "Date: 2026-04-01. Also 1 April 2026."
        assert extract_date_from_text(text) == "2026-04-01"


# ---------------------------------------------------------------------------
# extract_times_from_text
# ---------------------------------------------------------------------------

class TestExtractTimes:
    def test_24h_single_time(self):
        start, end = extract_times_from_text("event at 14:30")
        assert start == "14:30"

    def test_24h_time_range(self):
        start, end = extract_times_from_text("14:00 to 18:00")
        assert start == "14:00"
        assert end == "18:00"

    def test_12h_format(self):
        start, end = extract_times_from_text("event at 2pm")
        assert start == "14:00"

    def test_12h_with_minutes(self):
        start, end = extract_times_from_text("starts at 2:30 PM")
        assert start == "14:30"

    def test_midnight_am(self):
        start, end = extract_times_from_text("starts at 12 am")
        assert start == "00:00"

    def test_noon_pm(self):
        start, end = extract_times_from_text("starts at 12 pm")
        assert start == "12:00"

    def test_empty_string(self):
        start, end = extract_times_from_text("")
        assert start is None
        assert end is None

    def test_no_times(self):
        start, end = extract_times_from_text("no time here")
        assert start is None

    def test_duration_segment_removed(self):
        # Duration segment is stripped; time after it should be found
        start, end = extract_times_from_text("Event at 14:00. Duration: 2 hours")
        assert start == "14:00"

    # --- 12h format edge cases ---

    def test_12h_am_dot_format(self):
        """'a.m.' with periods should be normalized and parsed."""
        start, end = extract_times_from_text("starts at 9 a.m.")
        assert start == "09:00"

    def test_12h_pm_dot_format(self):
        """'p.m.' with periods should be normalized and parsed."""
        start, end = extract_times_from_text("starts at 3 p.m.")
        assert start == "15:00"

    def test_12h_dot_separator(self):
        """2.30 PM — dot as minute separator."""
        start, end = extract_times_from_text("starts at 2.30 pm")
        assert start == "14:30"

    def test_12h_range(self):
        start, end = extract_times_from_text("2pm to 5pm")
        assert start == "14:00"
        assert end == "17:00"

    def test_24h_midnight(self):
        start, end = extract_times_from_text("doors open at 00:00")
        assert start == "00:00"

    def test_24h_end_of_day(self):
        start, end = extract_times_from_text("event at 23:59")
        assert start == "23:59"

    def test_mixed_12h_and_24h(self):
        """12h times are found before 24h; both should appear."""
        start, end = extract_times_from_text("doors at 2pm, show at 20:00")
        assert start == "14:00"
        assert end == "20:00"


# ---------------------------------------------------------------------------
# extract_location_from_text
# ---------------------------------------------------------------------------

class TestExtractLocation:
    def test_venue_prefix(self):
        result = extract_location_from_text("Venue: ETH Main Building")
        assert result is not None
        assert "ETH Main Building" in result

    def test_location_prefix(self):
        result = extract_location_from_text("Location: HG E 1.1")
        assert result is not None

    def test_ort_prefix(self):
        result = extract_location_from_text("Ort: Polyterrasse")
        assert result is not None
        assert "Polyterrasse" in result

    def test_eth_room_format(self):
        result = extract_location_from_text("The event is in HG E22")
        assert result is not None

    def test_empty_string(self):
        assert extract_location_from_text("") is None

    def test_no_location(self):
        assert extract_location_from_text("no location here at all") is None

    def test_where_prefix(self):
        result = extract_location_from_text("Where: Main Hall")
        assert result is not None
        assert "Main Hall" in result

    def test_room_prefix(self):
        result = extract_location_from_text("Room: CAB G 11")
        assert result is not None

    def test_raum_prefix(self):
        result = extract_location_from_text("Raum: HG D 1.1")
        assert result is not None

    def test_eth_room_with_dot(self):
        """ETH room codes like 'CAB G11.1' should match."""
        result = extract_location_from_text("Meet in CAB G11.1 for the event")
        assert result is not None


# ---------------------------------------------------------------------------
# extract_events_from_raw
# ---------------------------------------------------------------------------

class TestExtractEventsFromRaw:
    def test_basic_event(self):
        raw = {
            "metadata": {"title": "ETH Apero"},
            "url": "https://example.com/event",
            "content": "Join us on 2026-03-22 at 18:00. Location: HG E 1.1",
        }
        events = extract_events_from_raw(raw)
        assert len(events) == 1
        assert events[0]["title"] == "ETH Apero"
        assert events[0]["date"] == "2026-03-22"
        assert events[0]["url"] == "https://example.com/event"

    def test_empty_record(self):
        assert extract_events_from_raw({}) == []

    def test_no_title_no_date(self):
        raw = {"content": "some random text without dates"}
        assert extract_events_from_raw(raw) == []

    def test_title_but_no_date_returns_event(self):
        raw = {"metadata": {"title": "Mystery Event"}, "content": "come join us"}
        events = extract_events_from_raw(raw)
        assert len(events) == 1
        assert events[0]["title"] == "Mystery Event"
        assert events[0]["date"] is None

    def test_date_but_no_title_returns_untitled(self):
        raw = {"content": "event on 2026-03-22"}
        events = extract_events_from_raw(raw)
        assert len(events) == 1
        assert events[0]["title"] == "Untitled Event"

    def test_description_truncated(self):
        raw = {
            "metadata": {"title": "Test"},
            "content": "x" * 1000,
        }
        events = extract_events_from_raw(raw)
        assert len(events[0]["description"]) <= 500

    def test_og_title_fallback(self):
        raw = {
            "metadata": {"og:title": "OG Title"},
            "content": "2026-03-22",
        }
        events = extract_events_from_raw(raw)
        assert events[0]["title"] == "OG Title"

    def test_location_from_metadata(self):
        raw = {
            "metadata": {"title": "Event", "location": "ETH Zentrum"},
            "content": "2026-03-22",
        }
        events = extract_events_from_raw(raw)
        assert events[0]["location"] == "ETH Zentrum"
