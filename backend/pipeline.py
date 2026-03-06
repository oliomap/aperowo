"""Main pipeline orchestrator.

Runs all source adapters, extracts structured events, filters for food,
scores ease of entry, deduplicates, and writes data/events.json.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_sources
from .extraction.extractor import extract_events
from .filtering.food_detector import detect_food
from .filtering.gemini_validator import validate_events
from .filtering.refreshments import build_search_corpus, extract_text_fragments
from .filtering.validators import is_valid_event
from .logging_config import get_logger
from .scoring import ease_of_entry as keyword_scorer
from .scoring import gemini_scorer
from .normalize import make_event_id, is_duplicate

log = get_logger("aperowo.pipeline")

# ── Progress bar ──────────────────────────────────────────────────────────

_BAR_WIDTH = 30
_FILL = "━"
_EMPTY = "╌"
_DIM = "\033[2m"
_RESET = "\033[0m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_YELLOW = "\033[33m"


class _Progress:
    """Live console progress bar for pipeline sources."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.current = 0
        self.events_found = 0
        self.errors = 0
        self._start = time.monotonic()

    def advance(self, source_id: str, source_events: int, error: bool = False) -> None:
        self.current += 1
        self.events_found += source_events
        if error:
            self.errors += 1
        self._draw(source_id, source_events, error)

    def finish(self) -> None:
        elapsed = time.monotonic() - self._start
        mins, secs = divmod(int(elapsed), 60)
        sys.stderr.write("\r\033[K")  # clear the progress line
        sys.stderr.write(
            f"\n  {_BOLD}{_GREEN}✓{_RESET} {_BOLD}Done{_RESET} "
            f"{_DIM}─{_RESET} "
            f"{_CYAN}{self.events_found}{_RESET} events from "
            f"{_CYAN}{self.total}{_RESET} sources "
            f"{_DIM}in {mins}m {secs:02d}s{_RESET}"
        )
        if self.errors:
            sys.stderr.write(f"  {_YELLOW}({self.errors} failed){_RESET}")
        sys.stderr.write("\n\n")
        sys.stderr.flush()

    def _draw(self, source_id: str, source_events: int, error: bool) -> None:
        frac = self.current / self.total if self.total else 1
        filled = int(_BAR_WIDTH * frac)
        bar = (
            f"{_GREEN}{_FILL * filled}{_RESET}"
            f"{_DIM}{_EMPTY * (_BAR_WIDTH - filled)}{_RESET}"
        )
        pct = f"{frac * 100:3.0f}%"
        count = f"{self.current}/{self.total}"
        status = f"\033[31m✗{_RESET}" if error else f"{_GREEN}+{source_events}{_RESET}"
        # Truncate long source ids
        name = source_id[:20].ljust(20)
        line = f"  {bar}  {_DIM}{count}{_RESET}  {pct}  {name}  {status}"
        sys.stderr.write(f"\r\033[K{line}")
        sys.stderr.flush()

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "events.json"


# Max concurrent sources (limits Playwright browser instances)
_MAX_CONCURRENT = 5


async def run(output_path: Path | None = None) -> list[dict[str, Any]]:
    """Execute the full pipeline and write events.json.

    Returns the list of events written.
    """
    output_path = output_path or OUTPUT_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sources = load_sources()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("Pipeline: processing %d sources concurrently (max %d)...", len(sources), _MAX_CONCURRENT)
    progress = _Progress(len(sources))
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    # Phase 1: Process all sources concurrently
    tasks: list[asyncio.Task[list[dict[str, Any]]]] = []
    async with asyncio.TaskGroup() as tg:
        for source in sources:
            task = tg.create_task(
                _process_source(source, semaphore, progress, now)
            )
            tasks.append(task)

    # Collect results from all tasks
    all_events: list[dict[str, Any]] = []
    for task in tasks:
        all_events.extend(task.result())

    progress.finish()

    # Phase 2: Deduplicate across all sources
    # Sort by source then title for deterministic dedup ordering
    all_events.sort(key=lambda e: (e.get("source", ""), e.get("title", "")))
    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for event in all_events:
        title = event.get("title", "")
        if is_duplicate(title, seen_titles):
            log.debug("Duplicate skipped: %s", title)
            continue
        if title:
            seen_titles.add(title)
        deduped.append(event)

    # Phase 3: Gemini batch validation (single API call)
    log.info("Validating %d events with Gemini...", len(deduped))
    deduped = await validate_events(deduped)

    # Sort by date (events without dates go last)
    deduped.sort(key=lambda e: e.get("date") or "9999-99-99")

    # Write output
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    log.info("Pipeline complete: %d events written to %s", len(deduped), output_path)
    return deduped


async def _process_source(
    source: Any,
    semaphore: asyncio.Semaphore,
    progress: _Progress,
    now: str,
) -> list[dict[str, Any]]:
    """Process a single source end-to-end. Returns list of events (no dedup)."""
    events: list[dict[str, Any]] = []

    try:
        async with semaphore:
            log.info("[%s] Fetching...", source.source_id)
            try:
                raw_records = await source.fetch_raw()
            except Exception as exc:
                log.error("[%s] Error fetching: %s", source.source_id, exc, exc_info=True)
                progress.advance(source.source_id, 0, error=True)
                return []

            log.info("[%s] Got %d raw records, extracting events...", source.source_id, len(raw_records))

        for record in raw_records:
            if record.get("_pre_structured"):
                extracted = [{
                    "title": record.get("title", ""),
                    "date": record.get("date"),
                    "start_time": record.get("start_time"),
                    "end_time": record.get("end_time"),
                    "location": record.get("location"),
                    "url": record.get("url", ""),
                    "description": record.get("description", ""),
                }]
            else:
                try:
                    extracted = await extract_events(record)
                except Exception as exc:
                    log.error("[%s] Extraction error for %s: %s", source.source_id, record.get("url", "?"), exc, exc_info=True)
                    continue

            log.debug("[%s] Extracted %d events from %s", source.source_id, len(extracted), record.get("url", "?"))

            for event in extracted:
                food_result = detect_food(event)
                if not food_result and not record.get("_pre_structured"):
                    food_result = detect_food(record)
                if not food_result:
                    log.debug("[%s] No food detected: %s", source.source_id, event.get("title", "?"))
                    continue

                title = event.get("title", "")
                date = event.get("date")

                # Validate event quality
                valid, reason = is_valid_event(event)
                if not valid:
                    log.debug("[%s] Invalid event rejected (%s): %s", source.source_id, reason, title)
                    continue

                ease_result = await _score_ease(event, record)

                final = {
                    "id": make_event_id(source.source_id, title, date),
                    "source": source.source_id,
                    "title": title or "Untitled Event",
                    "date": date,
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "location": event.get("location"),
                    "url": _normalize_url(event.get("url", ""), source.source_id),
                    "food_type": food_result["food_type"],
                    "refreshments": food_result["refreshments"],
                    "refreshment_details": food_result["refreshment_details"],
                    "easeOfEntry": ease_result.get("score"),
                    "easeOfEntry_method": ease_result.get("method", "keyword"),
                    "scraped_at": now,
                }
                events.append(final)
                log.debug("[%s] + %s (%s) — %s, ease=%.2f (%s)",
                          source.source_id, title, date,
                          food_result["food_type"],
                          ease_result.get("score", 0),
                          ease_result.get("method", "?"))

        log.info("[%s] Found %d food events", source.source_id, len(events))
        progress.advance(source.source_id, len(events))
        return events
    except Exception as exc:
        log.error("[%s] Unexpected error: %s", source.source_id, exc, exc_info=True)
        progress.advance(source.source_id, 0, error=True)
        return []


async def _score_ease(
    event: dict[str, Any],
    raw_record: dict[str, Any],
) -> dict[str, Any]:
    """Score ease of entry: keywords first, Gemini only when ambiguous."""
    # Try keyword scoring first (free, instant)
    fragments = extract_text_fragments(event)
    fragments.extend(extract_text_fragments(raw_record))
    corpus = build_search_corpus(fragments)

    kw_result = keyword_scorer.score_ease_of_entry(
        corpus,
        price=raw_record.get("price"),
        spots=raw_record.get("spots"),
    )

    # If keywords gave a confident score, use it directly
    kw_score = kw_result["score"]
    if kw_score is not None and (kw_score >= 0.7 or kw_score <= 0.3):
        return {
            "score": kw_score,
            "method": "keyword",
            "signals": kw_result["signals"],
        }

    # Ambiguous or no signals — try Gemini for better judgement
    if gemini_scorer.is_available():
        result = await gemini_scorer.score_event(event)
        if result is not None:
            return result

    # Final fallback to keyword result (even if None/ambiguous)
    return {
        "score": kw_score,
        "method": "keyword",
        "signals": kw_result["signals"],
    }


def _normalize_url(url: str, source_id: str) -> str:
    """Ensure URLs are absolute."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    # AMIV relative URLs
    if source_id in ("amiv", "amiv-web"):
        return f"https://amiv.ethz.ch/{url.lstrip('/')}"
    return url
