"""Extraction dispatcher: tries Gemini first, falls back to regex.

Provides a unified interface for extracting structured event data
from raw crawled page records.
"""

from __future__ import annotations

from typing import Any

from . import gemini_extractor
from .regex_extractor import extract_events_from_raw
from ..logging_config import get_logger

log = get_logger("aperowo.extraction")


async def extract_events(raw_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structured events from a raw crawl record.

    Tries Gemini-powered extraction first (if API key is set).
    Falls back to regex-based extraction otherwise.
    """
    # Build content for Gemini from the best available field
    content = (
        raw_record.get("markdown")
        or raw_record.get("extracted_content")
        or raw_record.get("fit_html")
        or raw_record.get("html")
        or ""
    )
    source_url = raw_record.get("url", "")

    # Try Gemini first
    if gemini_extractor.is_available() and content.strip():
        log.debug("Trying Gemini extraction for %s", source_url)
        result = await gemini_extractor.extract_events_from_content(
            content, source_url=source_url
        )
        if result is not None:
            for event in result:
                if not event.get("url"):
                    event["url"] = source_url
            log.debug("Gemini returned %d events for %s", len(result), source_url)
            return result

    # Fallback to regex
    log.debug("Using regex fallback for %s", source_url)
    return extract_events_from_raw(raw_record)
