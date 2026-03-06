"""Single source of truth for refreshment keyword detection.

Defines REFRESHMENT_RULES used across the entire pipeline to detect
food, drinks, snacks, and desserts in event descriptions.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


REFRESHMENT_RULES: dict[str, dict[str, Any]] = {
    "drinks": {
        "label": "Drinks",
        "keywords": {
            "beer", "beverage", "beverages", "bier", "wine", "wein",
            "cocktail", "cocktails", "spritz", "hugos", "hugo",
            "gluhwein", "gluehwein", "champagne", "apero", "aperitivo",
            "drink", "shots", "longdrink",
        },
    },
    "food": {
        "label": "Food",
        "keywords": {
            "pizza", "pizzas", "burger", "burgers", "barbecue", "bbq",
            "grill", "bratwurst", "wuerstli", "wurst", "raclette",
            "fondue", "tapas", "buffet", "buffetts", "dinner", "meal",
            "meals", "supper", "lunch", "mittagessen", "abendessen",
            "food", "essen", "sushi",
        },
    },
    "snacks": {
        "label": "Snacks",
        "keywords": {
            "snack", "snacks", "bites", "chips", "nuts", "fingerfood",
            "finger food", "sandwich", "sandwiches", "apero riche",
        },
    },
    "sweet": {
        "label": "Dessert",
        "keywords": {
            "cake", "cakes", "brownie", "brownies", "cupcake", "cupcakes",
            "dessert", "desserts", "chocolate", "sweets", "waffle",
            "waffles", "crepe", "crepes", "ice cream", "gelato",
            "donut", "donuts",
        },
    },
}

REFRESHMENT_DISPLAY_PRIORITY = ["food", "drinks", "snacks", "sweet"]


def normalize_text(text: str) -> str:
    """Strip diacritical marks (accents) for robust keyword matching."""
    return "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )


def build_search_corpus(fragments: list[str]) -> str:
    """Build a normalized, whitespace-collapsed search corpus from text fragments."""
    cleaned = [
        normalize_text(fragment.lower()).strip()
        for fragment in fragments
        if fragment
    ]
    if not cleaned:
        return ""
    return re.sub(r"\s+", " ", " ".join(cleaned))


def _keyword_in_corpus(keyword: str, corpus: str) -> bool:
    normalized = normalize_text(keyword.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return False
    return bool(re.search(r"\b" + re.escape(normalized) + r"\b", corpus))


def match_refreshments(
    corpus: str,
    rules: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Match refreshment keywords against a pre-built corpus.

    Returns a dict with 'categories', 'matches', and 'summary' keys.
    """
    rules = rules or REFRESHMENT_RULES

    matches: dict[str, list[str]] = {}
    for category, config in rules.items():
        keywords = config.get("keywords", set()) or set()
        hits = sorted(
            kw for kw in keywords
            if kw and _keyword_in_corpus(kw, corpus)
        )
        if hits:
            matches[category] = hits

    if not matches:
        return {"categories": [], "matches": {}, "summary": None}

    ordered = [
        cat for cat in REFRESHMENT_DISPLAY_PRIORITY if cat in matches
    ] + [cat for cat in matches if cat not in REFRESHMENT_DISPLAY_PRIORITY]

    summary = _format_summary(ordered, matches, rules)
    return {"categories": ordered, "matches": matches, "summary": summary}


def _format_summary(
    categories: Sequence[str],
    matches: Mapping[str, Sequence[str]],
    rules: Mapping[str, Mapping[str, Any]],
) -> str:
    parts: list[str] = []
    for category in categories:
        label = rules.get(category, {}).get("label", category.title())
        keywords = list(matches.get(category, []))
        if not keywords:
            parts.append(label)
            continue
        snippet = ", ".join(keywords[:3])
        parts.append(f"{label} ({snippet})")
    return " · ".join(parts)


def extract_text_fragments(value: Any) -> list[str]:
    """Recursively extract all string fragments from a nested JSON value."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        fragments: list[str] = []
        for nested in value.values():
            fragments.extend(extract_text_fragments(nested))
        return fragments
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        fragments = []
        for item in value:
            fragments.extend(extract_text_fragments(item))
        return fragments
    return [str(value)]
