"""Gemini-powered batch validation of extracted events.

Makes a single API call to validate all events at once, checking for:
- False positives (events that don't actually offer free food)
- Missing or incorrect fields (location, date, time)
- Non-event pages (news articles, service pages, homepages)

Returns only the events that Gemini confirms as valid.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from google import genai

from ..gemini_rate_limit import gemini_lock, RATE_LIMIT_DELAY
from ..logging_config import get_logger

log = get_logger("aperowo.filtering.gemini_validator")

_VALIDATION_PROMPT = """You are validating a list of events scraped from ETH Zurich websites.
These events were detected as offering free food/drinks, but many may be false positives
from web scraping artifacts (CSS class names, navigation elements, page templates, etc.).

For each event, determine:
1. Is this a REAL event that actually offers free food/drinks? (not a news article, homepage, service page, or scraping artifact)
2. Are the extracted fields (title, date, time, location) reasonable?

Here are the events to validate (JSON array):

{events}

Return a JSON array of objects, one per input event, with these fields:
- "id": the event's id (copy from input)
- "valid": boolean — true if this is a real food event, false if it's a false positive
- "reason": string — brief explanation if invalid
- "corrected_title": string or null — if the title is a page template (like "Event Detail - Department..."), provide the actual event name if inferrable from the URL, otherwise null
- "corrected_location": string or null — if the location is wrong/missing, provide the correct one if inferrable, otherwise null

Return ONLY a valid JSON array. No markdown, no explanation.
"""

# Max events per batch (to stay within token limits)
_MAX_BATCH_SIZE = 50


def is_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def validate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate events using Gemini and return only valid ones (with corrections applied).

    If Gemini is unavailable, returns all events unchanged.
    """
    if not is_available() or not events:
        return events

    validated: list[dict[str, Any]] = []

    # Process in batches to stay within token limits
    for i in range(0, len(events), _MAX_BATCH_SIZE):
        batch = events[i:i + _MAX_BATCH_SIZE]
        result = await _validate_batch(batch)
        validated.extend(result)

    return validated


async def _validate_batch(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate a single batch of events."""
    # Build compact event summaries for the prompt
    summaries = []
    for e in events:
        summaries.append({
            "id": e["id"],
            "source": e.get("source", ""),
            "title": e.get("title", ""),
            "date": e.get("date"),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "location": e.get("location"),
            "url": e.get("url", ""),
            "food_type": e.get("food_type", ""),
        })

    prompt = _VALIDATION_PROMPT.format(events=json.dumps(summaries, ensure_ascii=False))
    events_by_id = {e["id"]: e for e in events}

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

        results = json.loads(text)
        if not isinstance(results, list):
            log.warning("Gemini validator returned non-list, keeping all events")
            return events

        validated = []
        for item in results:
            if not isinstance(item, dict):
                continue
            event_id = item.get("id")
            if event_id not in events_by_id:
                continue

            if not item.get("valid", True):
                log.info("Gemini rejected: %s (%s)", events_by_id[event_id].get("title", "?"), item.get("reason", ""))
                continue

            event = events_by_id.pop(event_id)

            # Apply corrections
            corrected_title = item.get("corrected_title")
            if corrected_title:
                event["title"] = corrected_title

            corrected_location = item.get("corrected_location")
            if corrected_location:
                event["location"] = corrected_location

            validated.append(event)

        # Include any events Gemini didn't mention (keep by default)
        for event in events_by_id.values():
            log.debug("Gemini didn't mention event %s, keeping it", event.get("title", "?"))
            validated.append(event)

        log.info("Gemini validation: %d/%d events passed", len(validated), len(events))
        return validated

    except Exception as exc:
        log.error("Gemini validation failed, keeping all events: %s", exc, exc_info=True)
        return events
