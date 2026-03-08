"""Extraction dispatcher: tries regex first, escalates to Gemini if needed.

Provides a unified interface for extracting structured event data
from raw crawled page records. Gemini is only called when regex
finds zero events on a crawled listing page, to conserve API quota.
Note: pre-structured records (API sources) skip extraction entirely.
"""

from __future__ import annotations

from typing import Any

from . import gemini_extractor
from .regex_extractor import extract_events_from_raw
from ..logging_config import get_logger

log = get_logger("aperowo.extraction")

# Minimum regex results before we skip Gemini.
# With 500 RPD on Gemini 3.1 Flash Lite, we can afford to use Gemini more.
_GEMINI_THRESHOLD = 2


async def extract_events(raw_record: dict[str, Any], *, is_subpage: bool = False) -> list[dict[str, Any]]:
    """Extract structured events from a raw crawl record.

    Tries regex first. Only escalates to Gemini when regex finds
    fewer than _GEMINI_THRESHOLD events, to conserve API quota.
    Subpages (individual event pages discovered via deep crawl) skip
    Gemini entirely since the parent listing page already handled extraction.
    """
    source_url = raw_record.get("url", "")

    # Try regex first (free, instant)
    regex_result = extract_events_from_raw(raw_record)
    if len(regex_result) >= _GEMINI_THRESHOLD:
        log.debug("Regex found %d events for %s, skipping Gemini", len(regex_result), source_url)
        return regex_result

    # Skip Gemini for subpages — they're individual event pages where
    # regex finding 1 event is expected and correct.
    if is_subpage:
        log.debug("Subpage %s: using regex result (%d events), skipping Gemini", source_url, len(regex_result))
        return regex_result

    # Regex found too few events — try Gemini for better extraction
    content = (
        raw_record.get("markdown")
        or raw_record.get("extracted_content")
        or raw_record.get("fit_html")
        or raw_record.get("html")
        or ""
    )

    if gemini_extractor.is_available() and content.strip():
        log.debug("Regex found %d events, trying Gemini for %s", len(regex_result), source_url)
        gemini_result = await gemini_extractor.extract_events_from_content(
            content, source_url=source_url
        )
        if gemini_result is not None and len(gemini_result) > len(regex_result):
            for event in gemini_result:
                if not event.get("url"):
                    event["url"] = source_url
            log.debug("Gemini found %d events for %s (regex had %d)", len(gemini_result), source_url, len(regex_result))
            return gemini_result
        if gemini_result is None:
            # Gemini was attempted but failed — mark the record so the
            # pipeline knows this URL wasn't fully processed.
            raw_record["_gemini_failed"] = True

    # Return whatever regex found (even if 0-1 events)
    return regex_result
