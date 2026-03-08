"""Deterministic validators to reject obviously bad events.

These catch common extraction artifacts: CSS class names parsed as food,
HTML button text as locations, page template titles as event names, etc.
"""

from __future__ import annotations

import re
from typing import Any

from ..logging_config import get_logger

log = get_logger("aperowo.filtering.validators")

# Locations that are clearly extraction artifacts
_GARBAGE_LOCATIONS = {"button", "us", "undefined", "null", "none", "n/a"}

# Title patterns that indicate a page template, not an actual event
_TEMPLATE_TITLE_PATTERNS = [
    re.compile(r"^(event\s*)?(detail|calendar)\s*(page)?\s*[–—-]", re.IGNORECASE),
    re.compile(r"^eventdetail\s*[–—-]", re.IGNORECASE),
    re.compile(r"^news\s*&?\s*events?\s*[–—-]", re.IGNORECASE),
    re.compile(r"^details?\s*[–—-]", re.IGNORECASE),
    re.compile(r"^homepage\s*-", re.IGNORECASE),
]

# Title patterns that indicate a news article, not an event
_NEWS_ARTICLE_INDICATORS = [
    "professors appointed",
    "professors emeriti",
    "how eth is",
    "| eth zurich\n",  # news articles typically have this suffix pattern
]


def is_valid_event(event: dict[str, Any]) -> tuple[bool, str]:
    """Check if an event passes basic quality validation.

    Returns (is_valid, reason) where reason explains rejection.
    """
    location = (event.get("location") or "").strip()
    title = (event.get("title") or "").strip()
    date = event.get("date") or ""
    start_time = event.get("start_time") or ""
    end_time = event.get("end_time") or ""

    # Reject garbage locations
    if location.lower() in _GARBAGE_LOCATIONS:
        return False, f"garbage location: '{location}'"

    # Reject prices parsed as locations (e.g. "CHF 15.00")
    if re.match(r"^CHF\s", location):
        return False, f"price as location: '{location}'"

    # Reject HTML fragments as locations
    if ".html" in location:
        return False, f"HTML fragment as location: '{location}'"

    # Reject page template titles
    for pattern in _TEMPLATE_TITLE_PATTERNS:
        if pattern.search(title):
            return False, f"page template title: '{title[:60]}'"

    # Reject events with very old dates (likely extraction errors)
    if date and date < "2025-01-01":
        return False, f"stale date: {date}"

    # Reject events where end_time < start_time and isn't a midnight crossover
    if start_time and end_time:
        if end_time < start_time and end_time > "06:00":
            return False, f"invalid time range: {start_time}-{end_time}"

    return True, ""
