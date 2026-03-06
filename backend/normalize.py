"""Text normalization, deduplication, and ID generation utilities."""

from __future__ import annotations

import re
from thefuzz import fuzz


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
    """Check if a similar title already exists using fuzzy matching."""
    if not title:
        return False
    for seen in seen_titles:
        if fuzz.partial_ratio(title, seen) >= threshold:
            return True
    return False
