"""Regex-based extraction of dates, times, and locations from text.

Ported from the original filter.py. Used as fallback when Gemini is unavailable.
"""

from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from backend.filtering.refreshments import normalize_text, extract_text_fragments

# ---------------------------------------------------------------------------
# Month name parsing
# ---------------------------------------------------------------------------

_MONTH_VARIANTS: dict[int, tuple[str, ...]] = {
    1: ("jan", "jan.", "january"),
    2: ("feb", "feb.", "february"),
    3: ("mar", "mar.", "march"),
    4: ("apr", "apr.", "april"),
    5: ("may",),
    6: ("jun", "jun.", "june"),
    7: ("jul", "jul.", "july"),
    8: ("aug", "aug.", "august"),
    9: ("sep", "sep.", "sept", "sept.", "september"),
    10: ("oct", "oct.", "october"),
    11: ("nov", "nov.", "november"),
    12: ("dec", "dec.", "december"),
}

_MONTH_ALIASES: dict[str, int] = {
    alias: month
    for month, aliases in _MONTH_VARIANTS.items()
    for alias in aliases
}

_MONTH_PATTERN = "|".join(
    sorted((re.escape(a) for a in _MONTH_ALIASES), key=len, reverse=True)
)
_MONTH_FIRST_RE = re.compile(
    rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)(?:,?\s*(\d{{2,4}}))?",
    re.IGNORECASE,
)
_DAY_FIRST_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})(?:,?\s*(\d{{2,4}}))?",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_EURO_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")

# ---------------------------------------------------------------------------
# Time parsing
# ---------------------------------------------------------------------------

_TIME_24H_RE = re.compile(r"\b(2[0-3]|[01]?\d):([0-5]\d)(?::([0-5]\d))?\b")
_TIME_12H_RE = re.compile(
    r"\b(1[0-2]|0?[1-9])(?:[:.]([0-5]\d))?\s*(am|pm)\b", re.IGNORECASE
)
_DURATION_SEGMENT_RE = re.compile(r"Duration:.*", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Location heuristics
# ---------------------------------------------------------------------------

_LOCATION_RE = re.compile(
    r"(?:Venue|Location|Ort|Where|Room|Raum)[:\-–]\s*([A-Za-z0-9 ,.\-/]+)",
    re.IGNORECASE,
)
_ETH_ROOM_RE = re.compile(
    r"\b([A-Z]{2,4}\s+[A-Z]?\d{1,3}(?:\.\d{1,2})?)\b"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_date_from_text(text: str) -> str | None:
    """Extract a YYYY-MM-DD date from text. Tries multiple formats."""
    if not text:
        return None

    m = _ISO_DATE_RE.search(text)
    if m:
        return _build_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    for m in _MONTH_FIRST_RE.finditer(text):
        month = _parse_month(m.group(1))
        day = _parse_day(m.group(2))
        year = _coerce_year(m.group(3))
        if month and day and year:
            iso = _build_iso(year, month, day)
            if iso:
                return iso

    for m in _DAY_FIRST_RE.finditer(text):
        day = _parse_day(m.group(1))
        month = _parse_month(m.group(2))
        year = _coerce_year(m.group(3))
        if month and day and year:
            iso = _build_iso(year, month, day)
            if iso:
                return iso

    for m in _EURO_DATE_RE.finditer(text):
        try:
            day, month = int(m.group(1)), int(m.group(2))
        except ValueError:
            continue
        year = _coerce_year(m.group(3))
        if year:
            iso = _build_iso(year, month, day)
            if iso:
                return iso

    return None


def extract_times_from_text(text: str) -> tuple[str | None, str | None]:
    """Extract start_time and end_time (HH:MM) from text."""
    if not text:
        return None, None

    cleaned = _DURATION_SEGMENT_RE.sub("", text)
    prepared = _prepare_time_text(cleaned)
    times = _find_time_minutes(prepared)

    start = _fmt_minutes(times[0]) if times else None
    end = None
    if len(times) >= 2:
        # Only treat second time as end_time if there's a range indicator between them
        end = _fmt_minutes(times[1])

    return start, end


def extract_location_from_text(text: str) -> str | None:
    """Try to extract a location/venue from text."""
    if not text:
        return None

    m = _LOCATION_RE.search(text)
    if m:
        return m.group(1).strip()

    m = _ETH_ROOM_RE.search(text)
    if m:
        return m.group(1).strip()

    return None


def extract_events_from_raw(raw_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structured event data from a raw crawl4ai record using regex.

    This is the fallback extractor when Gemini is not available.
    Each raw record may contain multiple events (or just one page with one event).
    For the regex approach, we treat each crawled page as potentially one event.
    """
    fragments = extract_text_fragments(raw_record)
    combined = " ".join(f for f in fragments if f)
    if not combined.strip():
        return []

    title = _extract_title(raw_record)
    url = raw_record.get("url", "")
    date = extract_date_from_text(combined)
    start_time, end_time = extract_times_from_text(combined)
    location = (
        _deep_get(raw_record, "metadata", "location")
        or _deep_get(raw_record, "location")
        or extract_location_from_text(combined)
    )

    if not title and not date:
        return []

    return [{
        "title": title or "Untitled Event",
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "url": url,
        "description": combined[:500],
    }]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_title(record: dict[str, Any]) -> str | None:
    for key_path in [
        ("metadata", "title"),
        ("title",),
        ("metadata", "og:title"),
    ]:
        val = _deep_get(record, *key_path)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _deep_get(d: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(d, Mapping):
            d = d.get(key)
        else:
            return None
    return d


def _parse_month(token: str | None) -> int | None:
    if not token:
        return None
    return _MONTH_ALIASES.get(token.strip().lower().rstrip("."))


def _parse_day(token: str | None) -> int | None:
    if not token:
        return None
    cleaned = re.sub(r"(st|nd|rd|th)$", "", token, flags=re.IGNORECASE)
    try:
        day = int(cleaned)
    except ValueError:
        return None
    return day if 1 <= day <= 31 else None


def _coerce_year(token: str | None) -> int | None:
    if not token or not token.strip():
        return None
    try:
        year = int(token.strip())
    except ValueError:
        return None
    if year < 100:
        return year + 2000 if year <= 49 else year + 1900
    return year


def _build_iso(year: int, month: int, day: int) -> str | None:
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _prepare_time_text(text: str) -> str:
    if not text:
        return ""
    def repl(m: re.Match[str]) -> str:
        return f"{m.group(1).lower()}m"
    return re.sub(r"(?i)\b([ap])\.?\s*m\.?\b\.?", repl, text)


def _find_time_minutes(text: str) -> list[int]:
    if not text:
        return []
    results: list[int] = []
    seen: set[int] = set()

    for m in _TIME_12H_RE.finditer(text):
        hour = int(m.group(1))
        minute = int(m.group(2) or "0")
        meridian = m.group(3).lower()
        if meridian == "pm" and hour != 12:
            hour += 12
        if meridian == "am" and hour == 12:
            hour = 0
        total = hour * 60 + minute
        if total not in seen:
            seen.add(total)
            results.append(total)

    for m in _TIME_24H_RE.finditer(text):
        total = int(m.group(1)) * 60 + int(m.group(2))
        if total not in seen:
            seen.add(total)
            results.append(total)

    return results


def _fmt_minutes(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"
