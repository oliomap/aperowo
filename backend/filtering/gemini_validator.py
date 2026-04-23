"""Gemini-powered batch validation and ease-of-entry scoring.

Makes a single API call per batch to both validate events and review their
keyword-based ease-of-entry scores. This combines what were previously two
separate Gemini phases into one to minimize API usage.

Returns only the events that Gemini confirms as valid, with updated scores.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai

from ..gemini_rate_limit import (
    gemini_lock,
    RATE_LIMIT_DELAY,
    get_api_key,
    rotate_key,
    is_quota_error,
    is_unavailable_error,
)
from ..logging_config import get_logger

log = get_logger("aperowo.filtering.gemini_validator")

_COMBINED_PROMPT = """You are reviewing a list of events scraped from ETH Zurich websites.
These events were detected as offering free food/drinks via keyword matching, but some may be false positives.
A keyword-based system has also proposed an ease-of-entry score for each event.

For each event, do TWO things:

1. VALIDATE: Is this a REAL event that actually offers free food/drinks?
   - Reject scraping artifacts (CSS class names, navigation elements, page templates)
   - Reject non-event pages (news articles, service pages, homepages)
   - Reject events that clearly don't offer free food/drinks
   - IMPORTANT: "Lunch seminars", "lunch talks", "brown bag sessions", research seminars at lunchtime, colloquia, and similar academic events do NOT offer free food just because they happen at lunchtime. The word "lunch" in titles like "Lunch Seminar" or "Research Seminar" (starting at 12:00) describes the TIME SLOT, not free food. Reject these unless the description explicitly mentions food/drinks being served (e.g. "pizza will be provided", "drinks and snacks", "apéro after the talk").
   - Similarly, reject events where food_type is only "Lunch", "Dinner", or "Mittagessen" unless the description explicitly confirms free food is part of the event

2. SCORE EASE OF ENTRY: Review the keyword-based score and revise it if needed.
   Score from 0.0 to 1.0 — how easy is it for a random ETH student to walk in and grab free food, whether officially invited or not.
   - 0.9-1.0: Anyone can walk in, no registration, free food clearly available (e.g. public apéro, open campus BBQ)
   - 0.7-0.8: Open student association events, talks with free food (pizza, snacks), casual sign-up forms, large lecture halls where blending in is trivial, networking/apéro events on campus where people mingle freely
   - 0.5-0.6: Members-preferred but not strictly enforced, or events where you need to actively register but access isn't checked
   - 0.3-0.4: Small private event with guest list, limited spots, or semi-closed gatherings
   - 0.1-0.2: Strictly controlled access, paid entry, invite-only with verification, or very exclusive
   - 0.0: Sold out, cancelled, or impossible to access

   IMPORTANT scoring guidelines:
   - Most ETH student association events (VIS, AMIV, VMP, etc.) with free food are EASY to attend (0.7+). Simple online sign-ups or "register" buttons are NOT real barriers — they rarely check attendance lists at the door.
   - Company talks/workshops at ETH that offer pizza/food should score 0.7+ unless explicitly limited to small groups.
   - Networking/apéro events ON CAMPUS (ETH buildings, foyers, lecture halls) are easy to blend into (0.7+). But networking events at company offices or external venues score lower (0.4-0.6) — these often have reception desks, badge checks, or small headcounts where you'd stand out.
   - Only score low (below 0.5) for genuinely restrictive events: paid entry, strict guest lists, private dinners with limited seats, or events requiring membership verification.
   - "Registration required" alone should NOT lower the score significantly — consider whether registration is actually enforced.

Here are the events to review:

{events}

Return a JSON array with one object per event:
- "id": the event's id (copy from input)
- "valid": boolean — true if real food event, false if false positive
- "reason": string — brief explanation (for rejection or score revision)
- "ease_of_entry": float (0.0-1.0) — your revised score (only needed if valid)
- "corrected_title": string or null — fix if title is a page template
- "corrected_location": string or null — fix if location is wrong/missing

Return ONLY a valid JSON array. No markdown, no explanation.
"""

# Max events per batch — balances detail per event with token limits
_MAX_BATCH_SIZE = 30

# Retry config for transient failures (503 overload, malformed JSON)
_MAX_ATTEMPTS = 4
_BACKOFF_SECONDS = (5.0, 15.0, 30.0)


def is_available() -> bool:
    return get_api_key() is not None


def _get_client() -> genai.Client:
    return genai.Client(api_key=get_api_key())


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from Gemini response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return text


async def validate_and_score_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate events and review ease-of-entry scores in a single Gemini call.

    Each event should have `_kw_ease_score` and `_kw_ease_signals` fields
    from the keyword scorer.

    If Gemini is unavailable, returns all events unchanged (keyword scores kept).
    """
    if not is_available() or not events:
        return events

    validated: list[dict[str, Any]] = []
    total_batches = -(-len(events) // _MAX_BATCH_SIZE)  # ceil division

    for i in range(0, len(events), _MAX_BATCH_SIZE):
        batch_num = i // _MAX_BATCH_SIZE + 1
        batch = events[i:i + _MAX_BATCH_SIZE]
        log.info("Gemini review batch %d/%d: processing %d events...", batch_num, total_batches, len(batch))
        result = await _process_batch(batch, batch_num=batch_num, total_batches=total_batches)
        validated.extend(result)

    return validated


async def _process_batch(events: list[dict[str, Any]], *, batch_num: int = 1, total_batches: int = 1) -> list[dict[str, Any]]:
    """Validate and score a single batch of events."""
    # Build event summaries including keyword scoring context
    summaries = []
    for e in events:
        kw_score = e.get("_kw_ease_score")
        kw_signals = e.get("_kw_ease_signals", [])
        score_str = f"{kw_score:.2f}" if kw_score is not None else "unknown"

        summaries.append({
            "id": e["id"],
            "source": e.get("source", ""),
            "title": e.get("title", ""),
            "description": (e.get("description", "") or "")[:300],
            "date": e.get("date"),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "location": e.get("location"),
            "url": e.get("url", ""),
            "food_type": e.get("food_type", ""),
            "keyword_ease_score": score_str,
            "keyword_signals": kw_signals,
        })

    prompt = _COMBINED_PROMPT.format(events=json.dumps(summaries, ensure_ascii=False))
    events_by_id = {e["id"]: e for e in events}

    for attempt in range(_MAX_ATTEMPTS):
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

            text = _strip_markdown_fences(response.text)
            try:
                results = json.loads(text)
            except json.JSONDecodeError as parse_exc:
                # Gemini occasionally returns two concatenated JSON docs or
                # trailing junk. Retry once; if still bad, give up on batch.
                if attempt < _MAX_ATTEMPTS - 1:
                    backoff = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                    log.warning(
                        "Gemini returned unparseable JSON (%s), retrying in %.0fs (attempt %d/%d)",
                        parse_exc, backoff, attempt + 1, _MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(backoff)
                    continue
                log.error("Gemini returned unparseable JSON after %d attempts, keeping keyword scores: %s",
                          _MAX_ATTEMPTS, parse_exc)
                return events

            if not isinstance(results, list):
                log.warning("Gemini returned non-list, keeping all events with keyword scores")
                return events

            validated = []
            scored = 0
            for item in results:
                if not isinstance(item, dict):
                    continue
                event_id = item.get("id")
                if event_id not in events_by_id:
                    continue

                # Validation: reject false positives
                if not item.get("valid", True):
                    log.info("Gemini rejected: %s (%s)", events_by_id[event_id].get("title", "?"), item.get("reason", ""))
                    events_by_id.pop(event_id)
                    continue

                event = events_by_id.pop(event_id)

                # Apply field corrections
                corrected_title = item.get("corrected_title")
                if corrected_title:
                    event["title"] = corrected_title

                corrected_location = item.get("corrected_location")
                if corrected_location:
                    event["location"] = corrected_location

                # Apply ease-of-entry score
                ease_score = item.get("ease_of_entry")
                if ease_score is not None:
                    event["easeOfEntry"] = max(0.0, min(1.0, float(ease_score)))
                    event["easeOfEntry_method"] = "gemini"
                    event["easeOfEntry_reason"] = str(item.get("reason", ""))
                    scored += 1

                validated.append(event)

            # Include any events Gemini didn't mention (keep with keyword scores)
            for event in events_by_id.values():
                log.debug("Gemini didn't mention event %s, keeping it", event.get("title", "?"))
                validated.append(event)

            rejected = len(events) - len(validated)
            log.info(
                "Gemini review batch %d/%d: %d/%d accepted, %d rejected, %d scores revised",
                batch_num, total_batches, len(validated), len(events), rejected, scored,
            )
            return validated

        except Exception as exc:
            if is_quota_error(exc) and rotate_key():
                log.warning("Quota exhausted during review, rotating to next API key")
                continue

            if is_unavailable_error(exc) and attempt < _MAX_ATTEMPTS - 1:
                backoff = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                # Try the other key on alternating attempts — capacity pressure
                # often hits keys independently.
                if attempt % 2 == 1 and rotate_key():
                    log.warning(
                        "Gemini 503 overload, rotating key and retrying in %.0fs (attempt %d/%d)",
                        backoff, attempt + 1, _MAX_ATTEMPTS,
                    )
                else:
                    log.warning(
                        "Gemini 503 overload, retrying in %.0fs (attempt %d/%d)",
                        backoff, attempt + 1, _MAX_ATTEMPTS,
                    )
                await asyncio.sleep(backoff)
                continue

            log.error("Gemini review failed, keeping all events: %s", exc, exc_info=True)
            return events

    log.error("Gemini review failed after %d attempts, keeping all events", _MAX_ATTEMPTS)
    return events
