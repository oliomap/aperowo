"""Tests for backend.scoring.ease_of_entry — keyword-based scoring."""

import pytest

from backend.scoring.ease_of_entry import score_ease_of_entry, _coerce_number


# ---------------------------------------------------------------------------
# score_ease_of_entry — empty / null inputs
# ---------------------------------------------------------------------------

class TestScoreEmptyInputs:
    def test_empty_string(self):
        result = score_ease_of_entry("")
        assert result == {"score": None, "signals": []}

    def test_whitespace_only(self):
        result = score_ease_of_entry("   ")
        assert result["score"] is None

    def test_no_signals_returns_none(self):
        result = score_ease_of_entry("a lecture about math")
        assert result["score"] is None
        assert result["signals"] == []


# ---------------------------------------------------------------------------
# Positive signals
# ---------------------------------------------------------------------------

class TestPositiveSignals:
    def test_no_registration(self):
        result = score_ease_of_entry("no registration required for this event")
        assert result["score"] is not None
        assert result["score"] > 1.0 - 0.01  # 1.0 base + 1.0 weight, clamped to 1.0
        assert "No registration required" in result["signals"]

    def test_open_to_everyone(self):
        result = score_ease_of_entry("open to all students and staff")
        assert "Open to everyone" in result["signals"]
        assert result["score"] == 1.0  # clamped

    def test_drop_in(self):
        result = score_ease_of_entry("first come first served")
        assert "Drop-in welcome" in result["signals"]

    def test_free_entry(self):
        result = score_ease_of_entry("free admission at the door")
        assert "Free entry" in result["signals"]

    def test_public_social_event(self):
        result = score_ease_of_entry("join us for the campus fest")
        assert "Public social event (easy to blend in)" in result["signals"]

    def test_public_campus_location(self):
        result = score_ease_of_entry("event at polyterrasse eth zentrum")
        assert any("campus location" in s.lower() for s in result["signals"])

    def test_large_department_event(self):
        result = score_ease_of_entry("graduation ceremony for all")
        assert any("department" in s.lower() or "university" in s.lower() for s in result["signals"])


# ---------------------------------------------------------------------------
# Negative signals
# ---------------------------------------------------------------------------

class TestNegativeSignals:
    def test_registration_required(self):
        result = score_ease_of_entry("registration required to attend")
        assert "Registration required" in result["signals"]
        assert result["score"] < 1.0

    def test_members_only(self):
        result = score_ease_of_entry("members only event")
        assert "Members only" in result["signals"]
        assert result["score"] < 1.0

    def test_sold_out(self):
        result = score_ease_of_entry("this event is sold out")
        assert "Event sold out" in result["signals"]
        assert result["score"] < 0.5

    def test_waitlist(self):
        result = score_ease_of_entry("join the waitlist")
        assert "Waitlist active" in result["signals"]

    def test_login_required(self):
        result = score_ease_of_entry("login required to register")
        assert "Login required" in result["signals"]

    def test_entry_fee(self):
        result = score_ease_of_entry("entry costs CHF 10")
        assert "Entry fee mentioned" in result["signals"]

    def test_invite_only(self):
        result = score_ease_of_entry("this is an invite-only event")
        assert "Invite-only / private event" in result["signals"]


# ---------------------------------------------------------------------------
# Positive guard: registration required + no registration
# ---------------------------------------------------------------------------

class TestPositiveGuard:
    def test_registration_skipped_when_no_registration_present(self):
        text = "no registration required. registration required notice on page."
        result = score_ease_of_entry(text)
        # Should NOT penalize because positive guard overrides
        assert "Registration required" not in result["signals"]
        assert "No registration required" in result["signals"]


# ---------------------------------------------------------------------------
# Remaining places
# ---------------------------------------------------------------------------

class TestRemainingPlaces:
    def test_zero_spots(self):
        result = score_ease_of_entry("remaining places: 0")
        assert "No spots remaining" in result["signals"]

    def test_few_spots(self):
        result = score_ease_of_entry("remaining places: 2")
        assert "Only a few spots left" in result["signals"]

    def test_limited_spots(self):
        result = score_ease_of_entry("remaining places: 7")
        assert "Limited spots available" in result["signals"]

    def test_plenty_of_spots(self):
        result = score_ease_of_entry("remaining places: 50")
        assert "Plenty of spots available" in result["signals"]


# ---------------------------------------------------------------------------
# Structured price / spots
# ---------------------------------------------------------------------------

class TestStructuredInputs:
    def test_free_price(self):
        result = score_ease_of_entry("some apero event", price=0)
        assert "Free entry (structured)" in result["signals"]

    def test_paid_price(self):
        result = score_ease_of_entry("some apero event", price=15)
        assert "Paid entry (structured)" in result["signals"]

    def test_no_availability(self):
        result = score_ease_of_entry("some apero event", spots=0)
        assert "No availability (structured)" in result["signals"]

    def test_plenty_spots(self):
        result = score_ease_of_entry("some apero event", spots=100)
        assert "Plenty of spots (structured)" in result["signals"]

    def test_very_limited_spots(self):
        result = score_ease_of_entry("some apero event", spots=2)
        assert "Very limited spots (structured)" in result["signals"]

    def test_string_price(self):
        result = score_ease_of_entry("some apero event", price="0")
        assert "Free entry (structured)" in result["signals"]


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:
    def test_score_never_exceeds_1(self):
        text = "no registration required open to all free entry apero polyterrasse graduation"
        result = score_ease_of_entry(text)
        assert result["score"] <= 1.0

    def test_score_never_below_0(self):
        text = "sold out members only waitlist login required CHF invite-only"
        result = score_ease_of_entry(text)
        assert result["score"] >= 0.0


# ---------------------------------------------------------------------------
# _coerce_number
# ---------------------------------------------------------------------------

class TestCoerceNumber:
    def test_int(self):
        assert _coerce_number(42) == 42.0

    def test_float(self):
        assert _coerce_number(3.14) == 3.14

    def test_string_int(self):
        assert _coerce_number("10") == 10.0

    def test_string_comma_decimal(self):
        assert _coerce_number("3,14") == 3.14

    def test_none(self):
        assert _coerce_number(None) is None

    def test_bool(self):
        assert _coerce_number(True) is None
        assert _coerce_number(False) is None

    def test_empty_string(self):
        assert _coerce_number("") is None

    def test_non_numeric_string(self):
        assert _coerce_number("hello") is None

    def test_whitespace_string(self):
        assert _coerce_number("  ") is None
