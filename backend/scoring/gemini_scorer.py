"""Gemini-powered ease-of-entry scoring.

Uses gemini-2.5-flash to evaluate how easy it is for a random student
to walk in and get free food at an event. Falls back gracefully when
no API key is set.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from google import genai

from ..gemini_rate_limit import gemini_lock, RATE_LIMIT_DELAY
from ..logging_config import get_logger

log = get_logger("aperowo.scoring.gemini")


SCORING_PROMPT = """You are evaluating how easy it is for a random ETH Zurich student to grab free food at this event — whether officially invited or not.

Event details:
- Title: {title}
- Description: {description}
- Location: {location}
- Date/Time: {date} {start_time}
- Food offered: {food_type}

Score the "ease of entry" from 0.0 to 1.0 using this rubric:
- 0.9-1.0: Anyone can walk in, no registration, free food clearly available (e.g. public apéro, open campus BBQ)
- 0.7-0.8: Large crowd or public space where you could easily blend in and grab food unnoticed, even if technically members-only. Or: open event, just need to be an ETH student
- 0.5-0.6: Registration required but straightforward, or members-preferred but not strictly enforced. Medium-sized event in an accessible location
- 0.3-0.4: Small private event with a guest list, but in a semi-public space (e.g. a department lounge) where showing up might still work
- 0.1-0.2: Strictly controlled access, paid entry, very limited spots, or invite-only in a locked room
- 0.0: Sold out, cancelled, or impossible to access

Key factors to weigh:
- Is registration or a ticket required? Is it free?
- How large is the event? Big events (100+ people) are easier to blend into
- Is the location public (campus square, main hall) or private (locked seminar room)?
- Could someone realistically just walk up, grab a plate, and blend in with the crowd?
- Is it a department-wide or university-wide event (easier) vs. a small club meeting (harder)?

Return ONLY a JSON object: {{"score": <float>, "reason": "<one sentence explanation>"}}
"""



def is_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def score_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Score an event's ease of entry using Gemini.

    Returns {"score": float, "method": "gemini", "signals": [reason]}
    or None if Gemini is unavailable.
    """
    if not is_available():
        return None

    prompt = SCORING_PROMPT.format(
        title=event.get("title", ""),
        description=(event.get("description", "") or "")[:1000],
        location=event.get("location", "") or "Unknown",
        date=event.get("date", "") or "Unknown",
        start_time=event.get("start_time", "") or "Unknown",
        food_type=event.get("food_type", "") or "Unknown",
    )

    try:
        async with gemini_lock:
            client = _get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=prompt,
                config={"temperature": 0.1, "response_mime_type": "application/json"},
            )
            await asyncio.sleep(RATE_LIMIT_DELAY)

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        score = float(result.get("score", 0.5))
        score = max(0.0, min(1.0, score))
        reason = str(result.get("reason", ""))

        return {
            "score": score,
            "method": "gemini",
            "signals": [reason] if reason else [],
        }

    except Exception as exc:
        log.error("Gemini scoring failed for '%s': %s", event.get("title", ""), exc, exc_info=True)
        return None
