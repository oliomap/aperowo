"""Keyword-based ease-of-entry scoring.

Estimates how easy it is for a random student to walk in and get free food.
Used as the fallback when Gemini is not available.
"""

from __future__ import annotations

import re
from typing import Any

from backend.filtering.refreshments import normalize_text

_KEYWORD_RULES: tuple[dict[str, Any], ...] = (
    {
        "pattern": re.compile(
            r"\b(no registration required|no registration needed|keine anmeldung erforderlich|keine anmeldung notig|ohne anmeldung)\b"
        ),
        "weight": 1.0,
        "label": "No registration required",
    },
    {
        "pattern": re.compile(
            r"\b(first[-\s]?come[-\s]?first[-\s]?served|walk[-\s]?in|drop[-\s]?in|walk in|drop in)\b"
        ),
        "weight": 0.75,
        "label": "Drop-in welcome",
    },
    {
        "pattern": re.compile(
            r"\b(open to all|everyone welcome|alle willkommen|offen fur alle)\b"
        ),
        "weight": 1.0,
        "label": "Open to everyone",
    },
    {
        "pattern": re.compile(
            r"\b(free entry|free admission|kostenloser eintritt|gratis eintritt|kein eintritt)\b"
        ),
        "weight": 0.6,
        "label": "Free entry",
    },
    {
        "pattern": re.compile(
            r"\b(registration required|registration opens|registration closes|sign up|signup|anmeldung erforderlich|anmeldung notig|anmeldung pflicht)\b"
        ),
        "weight": -0.2,
        "label": "Registration required",
    },
    {
        "pattern": re.compile(
            r"\b(log ?in required|login required|log in to register|einloggen erforderlich)\b"
        ),
        "weight": -0.3,
        "label": "Login required",
    },
    {
        "pattern": re.compile(
            r"\b(members only|nur fur mitglieder|only for members)\b"
        ),
        "weight": -0.4,
        "label": "Members only",
    },
    {
        "pattern": re.compile(r"\b(waitlist|wait list|warteliste)\b"),
        "weight": -0.4,
        "label": "Waitlist active",
    },
    {
        "pattern": re.compile(r"\b(sold out|ausgebucht|fully booked|ausverkauft)\b"),
        "weight": -0.6,
        "label": "Event sold out",
    },
    {
        "pattern": re.compile(r"\b(chf|fr\.)\b"),
        "weight": -0.2,
        "label": "Entry fee mentioned",
    },
    # Blendability: large/public events are easy to slip into
    {
        "pattern": re.compile(
            r"\b(apero|aperitif|apéro|campus\s*fest|campus\s*party|sommerfest|grillfest|bbq|barbecue|block\s*party)\b"
        ),
        "weight": 0.3,
        "label": "Public social event (easy to blend in)",
    },
    {
        "pattern": re.compile(
            r"\b(graduation|diploma|abschlussfeier|semesterendfeier|dies academicus|department\s*event|fakultat)\b"
        ),
        "weight": 0.2,
        "label": "Large department/university event",
    },
    {
        "pattern": re.compile(
            r"\b(hauptgebaude|hg\b|polyterrasse|lichthof|mensa|food\s*court|eth\s*zentrum|hoengg)\b"
        ),
        "weight": 0.15,
        "label": "Public campus location",
    },
    {
        "pattern": re.compile(
            r"\b(invite[- ]?only|einladung|auf einladung|invitation only|private event|geschlossene gesellschaft)\b"
        ),
        "weight": -0.35,
        "label": "Invite-only / private event",
    },
)

_POSITIVE_GUARDS: tuple[str, ...] = (
    "no registration required",
    "no registration needed",
    "keine anmeldung erforderlich",
    "ohne anmeldung",
)

_REMAINING_PLACES_RE = re.compile(
    r"(?:remaining (?:places|slots)|restplatze|freie platze)\s*[:=]\s*(\d+)"
)


def score_ease_of_entry(
    corpus: str,
    *,
    price: Any = None,
    spots: Any = None,
) -> dict[str, Any]:
    """Score ease of entry from 0.0 (impossible) to 1.0 (walk right in).

    Returns {"score": float | None, "signals": list[str]}.
    """
    if not corpus:
        return {"score": None, "signals": []}

    text = normalize_text(corpus.lower()).strip()
    if not text:
        return {"score": None, "signals": []}

    score = 1.0
    signals: list[str] = []

    for rule in _KEYWORD_RULES:
        if not rule["pattern"].search(text):
            continue
        label = rule["label"]
        weight = float(rule["weight"])

        if weight < 0 and label == "Registration required":
            if any(guard in text for guard in _POSITIVE_GUARDS):
                continue

        score += weight
        signals.append(label)

    # Remaining places
    match = _REMAINING_PLACES_RE.search(text)
    if match:
        try:
            remaining = int(match.group(1))
        except ValueError:
            remaining = None
        if remaining is not None:
            if remaining <= 0:
                score -= 0.4
                signals.append("No spots remaining")
            elif remaining <= 3:
                score -= 0.2
                signals.append("Only a few spots left")
            elif remaining <= 10:
                score -= 0.05
                signals.append("Limited spots available")
            elif remaining >= 25:
                score += 0.15
                signals.append("Plenty of spots available")

    # Structured price
    price_val = _coerce_number(price)
    if price_val is not None:
        if price_val <= 0:
            score += 0.25
            signals.append("Free entry (structured)")
        else:
            score -= 0.35
            signals.append("Paid entry (structured)")

    # Structured spots
    spots_val = _coerce_number(spots)
    if spots_val is not None:
        if spots_val <= 0:
            score -= 0.4
            signals.append("No availability (structured)")
        elif spots_val <= 3:
            score -= 0.2
            signals.append("Very limited spots (structured)")
        elif spots_val >= 25:
            score += 0.15
            signals.append("Plenty of spots (structured)")

    if not signals:
        return {"score": None, "signals": []}

    return {"score": max(0.0, min(1.0, score)), "signals": signals}


def _coerce_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None
