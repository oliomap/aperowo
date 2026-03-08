"""Gemini-powered structured event extraction from crawled page content.

Uses gemini-3.1-flash-lite-preview to parse markdown/HTML into structured event data.
Returns None if GEMINI_API_KEY is not set, allowing the caller to fall back
to regex-based extraction.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai

from ..gemini_rate_limit import gemini_lock, RATE_LIMIT_DELAY, get_api_key, rotate_key, is_quota_error
from ..logging_config import get_logger

log = get_logger("aperowo.extraction.gemini")

EXTRACTION_PROMPT = """You are extracting event information from a webpage about events at ETH Zurich.

Given this page content:

{content}

Extract ALL individual events mentioned on this page. For each event, return a JSON array where each element has exactly these keys:
- "title": string — event name
- "date": string — in YYYY-MM-DD format (null if not found)
- "start_time": string — in HH:MM 24-hour format (null if not found)
- "end_time": string — in HH:MM 24-hour format (null if not found)
- "location": string — venue, room, or address (null if not found)
- "url": string — direct link to the event page (null if not found)
- "description": string — brief description (max 200 chars)
- "has_food": boolean — does this event explicitly mention free food, drinks, or apéro?
- "food_type": string — what specific food/drinks are mentioned (null if none)

Important:
- Only include events that are actual upcoming events (not past events, not general info)
- For "has_food", look for keywords like: apéro, food, drinks, beer, pizza, BBQ, buffet, snacks, wine, etc.
- Return ONLY a valid JSON array. No markdown, no explanation.
- If no events are found, return []
"""



def is_available() -> bool:
    """Check if Gemini extraction is available (API key set)."""
    return get_api_key() is not None


def _get_client() -> genai.Client:
    return genai.Client(api_key=get_api_key())


async def extract_events_from_content(
    content: str,
    source_url: str = "",
) -> list[dict[str, Any]] | None:
    """Extract structured events from page content using Gemini.

    Returns None if Gemini is not available (caller should use regex fallback).
    Returns a list of event dicts on success.
    """
    if not is_available():
        return None

    if not content or not content.strip():
        return []

    # Truncate very long content to stay within token limits
    truncated = content[:15000] if len(content) > 15000 else content

    prompt = EXTRACTION_PROMPT.format(content=truncated)

    log.debug("Sending extraction request to Gemini for %s (%d chars)", source_url, len(truncated))

    last_exc = None
    for _attempt in range(2):
        try:
            async with gemini_lock:
                client = _get_client()
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-3.1-flash-lite-preview",
                    contents=prompt,
                    config={"temperature": 0.1, "response_mime_type": "application/json"},
                )
                await asyncio.sleep(RATE_LIMIT_DELAY)

            text = response.text.strip()
            # Clean potential markdown wrapping
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            try:
                events = json.loads(text)
            except json.JSONDecodeError:
                # Gemini sometimes returns multiple JSON values on separate lines;
                # parse each line and merge arrays.
                events = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        part = json.loads(line)
                        if isinstance(part, list):
                            events.extend(part)
                        elif isinstance(part, dict):
                            events.append(part)
                    except json.JSONDecodeError:
                        continue
                if not events:
                    log.warning("Could not parse Gemini response for %s", source_url)
                    return []
            if not isinstance(events, list):
                events = [events] if isinstance(events, dict) else []

            # Validate and clean each event
            validated = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                if not event.get("title"):
                    continue
                validated.append({
                    "title": str(event.get("title", "")),
                    "date": event.get("date"),
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "location": event.get("location"),
                    "url": event.get("url") or source_url,
                    "description": str(event.get("description", ""))[:500],
                    "has_food": bool(event.get("has_food", False)),
                    "food_type": event.get("food_type"),
                })

            log.debug("Gemini extracted %d events from %s", len(validated), source_url)
            return validated

        except Exception as exc:
            if is_quota_error(exc) and rotate_key():
                log.warning("Quota exhausted, rotating to next API key for %s", source_url)
                continue
            log.error("Gemini extraction failed for %s: %s", source_url, exc, exc_info=True)
            return None

    log.error("Gemini extraction failed for %s: all API keys exhausted", source_url)
    return None
