"""Text normalization, deduplication, and ID generation utilities."""

from __future__ import annotations

import re

try:
    from thefuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore[assignment]


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text[:60].strip("-")


def make_event_id(source: str, title: str, date: str | None) -> str:
    """Generate a stable composite event ID."""
    slug = slugify(title) if title else "event"
    date_part = date or "nodate"
    return f"{source}-{slug}-{date_part}"


def is_duplicate(title: str, seen_titles: set[str], threshold: int = 80) -> bool:
    """Check if a similar title already exists using fuzzy matching.

    Falls back to exact (case-insensitive) matching when *thefuzz* is not
    installed — this keeps the test suite runnable in minimal CI environments.
    """
    if not title:
        return False
    if fuzz is not None:
        for seen in seen_titles:
            if fuzz.partial_ratio(title, seen) >= threshold:
                return True
        return False
    # Fallback: exact case-insensitive comparison
    title_lower = title.lower()
    return any(title_lower == s.lower() for s in seen_titles)
