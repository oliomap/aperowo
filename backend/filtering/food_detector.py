"""Determine whether an event offers free food and build a food_type summary."""

from __future__ import annotations

from typing import Any

from .refreshments import (
    build_search_corpus,
    extract_text_fragments,
    match_refreshments,
)


def detect_food(event: dict[str, Any]) -> dict[str, Any] | None:
    """Check if an event mentions free food/drinks.

    Returns a dict with 'refreshments', 'refreshment_details', and 'food_type'
    if food-related keywords are found. Returns None otherwise.
    """
    fragments = extract_text_fragments(event)
    corpus = build_search_corpus(fragments)
    if not corpus:
        return None

    details = match_refreshments(corpus)
    if not details["categories"]:
        return None

    food_type = _build_food_type(details)
    return {
        "refreshments": details["summary"],
        "refreshment_details": details,
        "food_type": food_type,
    }


def _build_food_type(details: dict[str, Any]) -> str:
    """Build a concise food_type string from refreshment details.

    E.g. "Pizza, Beer, Snacks" — takes the top keywords from each category.
    """
    items: list[str] = []
    for category in details.get("categories", []):
        keywords = details.get("matches", {}).get(category, [])
        items.extend(kw.title() for kw in keywords[:2])
    return ", ".join(items) if items else "Food & Drinks"
