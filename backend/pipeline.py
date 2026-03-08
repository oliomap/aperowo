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
from .filtering.gemini_validator import validate_and_score_events
from .filtering.refreshments import build_search_corpus, extract_text_fragments
from .filtering.validators import is_valid_event
from .logging_config import get_logger, set_active_progress, _console_lock
from .scoring import ease_of_entry as keyword_scorer
from .normalize import make_event_id, is_duplicate
from . import visited_urls

log = get_logger("aperowo.pipeline")

# ── Progress display ─────────────────────────────────────────────────────

_BAR_WIDTH = 30
_FILL = "━"
_EMPTY = "╌"
_DIM = "\033[2m"
_RESET = "\033[0m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_YELLOW = "\033[33m"

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _Progress:
    """Multi-line progress display pinned to the bottom of the terminal.

    Shows an overall progress bar plus one spinner line per active source.
    The ProgressAwareHandler in logging_config clears the block before
    each log message and redraws it after, so logs scroll above while
    the progress block stays at the bottom.
    """

    def __init__(self, total: int, max_slots: int) -> None:
        self.total = total
        self.current = 0
        self.events_found = 0
        self.errors = 0
        self._start = time.monotonic()
        self._max_slots = max_slots
        self._active: dict[str, str] = {}   # source_id → status
        self._spin_idx = 0
        # How many lines the last _redraw wrote (used by ProgressAwareHandler)
        self._rendered_lines = 0

        set_active_progress(self)
        with _console_lock:
            self._redraw()

    # ── Public API ────────────────────────────────────────────────────

    def source_start(self, source_id: str) -> None:
        self._active[source_id] = "fetching…"
        with _console_lock:
            self._redraw()

    def source_status(self, source_id: str, status: str) -> None:
        if source_id in self._active:
            self._active[source_id] = status
            with _console_lock:
                self._redraw()

    def source_done(self, source_id: str, source_events: int, error: bool = False) -> None:
        self.current += 1
        self.events_found += source_events
        if error:
            self.errors += 1
        self._active.pop(source_id, None)
        with _console_lock:
            self._redraw()

    def finish(self) -> None:
        with _console_lock:
            self._clear()
            set_active_progress(None)

            elapsed = time.monotonic() - self._start
            mins, secs = divmod(int(elapsed), 60)
            sys.stderr.write(
                f"  {_BOLD}{_GREEN}✓{_RESET} {_BOLD}Done{_RESET} "
                f"{_DIM}─{_RESET} "
                f"{_CYAN}{self.events_found}{_RESET} events from "
                f"{_CYAN}{self.total}{_RESET} sources "
                f"{_DIM}in {mins}m {secs:02d}s{_RESET}"
            )
            if self.errors:
                sys.stderr.write(f"  {_YELLOW}({self.errors} failed){_RESET}")
            sys.stderr.write("\n\n")
            sys.stderr.flush()

    # ── Drawing internals ─────────────────────────────────────────────

    def _clear(self) -> None:
        """Erase the currently rendered progress block."""
        if self._rendered_lines > 0:
            sys.stderr.write(f"\033[{self._rendered_lines}A")
            for _ in range(self._rendered_lines):
                sys.stderr.write("\033[K\n")
            sys.stderr.write(f"\033[{self._rendered_lines}A")
            self._rendered_lines = 0
            sys.stderr.flush()

    def _redraw(self) -> None:
        """Clear and redraw the entire progress block."""
        self._clear()
        self._spin_idx = (self._spin_idx + 1) % len(_SPINNER)
        spinner = _SPINNER[self._spin_idx]

        lines: list[str] = []

        # Separator
        lines.append(f"  {_DIM}{'─' * 60}{_RESET}")

        # Overall progress bar
        frac = self.current / self.total if self.total else 0
        filled = int(_BAR_WIDTH * frac)
        bar = (
            f"{_GREEN}{_FILL * filled}{_RESET}"
            f"{_DIM}{_EMPTY * (_BAR_WIDTH - filled)}{_RESET}"
        )
        pct = f"{frac * 100:3.0f}%"
        count = f"{self.current}/{self.total}"
        lines.append(
            f"  {bar}  {_DIM}{count}{_RESET}  {pct}  "
            f"{_DIM}{self.events_found} events{_RESET}"
        )

        # Active source lines (up to max_slots)
        for sid, status in list(self._active.items())[:self._max_slots]:
            name = sid[:20].ljust(20)
            lines.append(f"    {_CYAN}{spinner}{_RESET} {name} {_DIM}{status}{_RESET}")

        output = "\n".join(lines) + "\n"
        sys.stderr.write(output)
        sys.stderr.flush()
        self._rendered_lines = len(lines)

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "events.json"


# Max concurrent sources (limits Playwright browser instances)
_MAX_CONCURRENT = 5


async def run(output_path: Path | None = None) -> list[dict[str, Any]]:
    """Execute the full pipeline and write events.json.

    Returns the list of events written.
    """
    output_path = output_path or OUTPUT_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load visited URLs cache to skip already-scraped event URLs
    visited_urls.load()

    sources = load_sources()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("Pipeline: processing %d sources concurrently (max %d)...", len(sources), _MAX_CONCURRENT)
    progress = _Progress(len(sources), max_slots=_MAX_CONCURRENT)
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
    log.info("Deduplicating %d raw events across sources...", len(all_events))
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
    log.info("Deduplicated to %d unique events (removed %d duplicates)",
             len(deduped), len(all_events) - len(deduped))

    # Phase 3: Gemini batch validation + ease-of-entry scoring (single API call)
    log.info("Validating and scoring %d events with Gemini...", len(deduped))
    deduped = await validate_and_score_events(deduped)

    # Clean up temporary fields
    for event in deduped:
        event.pop("_kw_ease_score", None)
        event.pop("_kw_ease_signals", None)
        event.pop("_pre_structured", None)
        event.pop("description", None)

    # Phase 4: Merge with existing events.json
    merged = _merge_events(output_path, deduped)

    # Sort by date (events without dates go last)
    merged.sort(key=lambda e: e.get("date") or "9999-99-99")

    # Write output
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    log.info("Pipeline complete: %d events written to %s (%d new, %d existing)",
             len(merged), output_path, len(deduped),
             len(merged) - len(deduped))
    return merged


def _merge_events(
    output_path: Path,
    new_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge newly scraped events into the existing events.json.

    - New events (by id) are added
    - Re-scraped events (same id) are updated with fresh data
    - Existing events not in this run are kept (they came from earlier runs)
    """
    log.info("Merging %d new events with existing %s...", len(new_events), output_path.name)

    existing: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                existing = json.load(f)
            log.info("Loaded %d existing events from %s", len(existing), output_path)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read existing events.json, starting fresh: %s", exc)

    if not existing:
        log.info("No existing events, writing %d new events", len(new_events))
        return new_events

    # Index new events by id for fast lookup
    new_by_id: dict[str, dict[str, Any]] = {e["id"]: e for e in new_events}

    # Start with all new events, then add existing ones that weren't re-scraped
    merged_by_id: dict[str, dict[str, Any]] = dict(new_by_id)
    kept = 0
    updated = 0
    for event in existing:
        eid = event.get("id", "")
        if eid in new_by_id:
            updated += 1
        elif eid not in merged_by_id:
            merged_by_id[eid] = event
            kept += 1

    log.info("Merge result: %d new, %d updated, %d kept from previous runs",
             len(new_by_id) - updated, updated, kept)

    # Deduplicate across old + new by title (in case titles match but ids differ)
    merged = list(merged_by_id.values())
    seen_titles: set[str] = set()
    final: list[dict[str, Any]] = []
    # Process new events first so they take priority over stale existing ones
    merged.sort(key=lambda e: (0 if e["id"] in new_by_id else 1, e.get("source", ""), e.get("title", "")))
    for event in merged:
        title = event.get("title", "")
        if is_duplicate(title, seen_titles):
            log.debug("Cross-dedup removed: %s", title)
            continue
        if title:
            seen_titles.add(title)
        final.append(event)

    cross_deduped = len(merged) - len(final)
    if cross_deduped:
        log.info("Cross-dedup removed %d events with similar titles across old/new", cross_deduped)

    log.info("Final merged total: %d events", len(final))
    return final


async def _process_source(
    source: Any,
    semaphore: asyncio.Semaphore,
    progress: _Progress,
    now: str,
) -> list[dict[str, Any]]:
    """Process a single source end-to-end. Returns list of events (no dedup)."""
    events: list[dict[str, Any]] = []

    try:
        progress.source_start(source.source_id)
        async with semaphore:
            log.info("[%s] Fetching...", source.source_id)
            try:
                raw_records = await source.fetch_raw()
            except Exception as exc:
                log.error("[%s] Error fetching: %s", source.source_id, exc, exc_info=True)
                progress.source_done(source.source_id, 0, error=True)
                return []

            log.info("[%s] Got %d raw records, extracting events...", source.source_id, len(raw_records))
            progress.source_status(source.source_id, f"extracting ({len(raw_records)} records)")

        source_base_url = source.config.get("url", "")
        source_base_norm = source_base_url.rstrip("/")

        # Build set of crawled subpage URLs (pages discovered via BFS that
        # are NOT the source's starting URL).  These represent real event
        # detail pages whose URLs are safe to cache as "visited".
        subpage_urls: set[str] = set()
        errored_urls: set[str] = set()
        successfully_scraped: set[str] = set()   # subpage URLs scraped without error
        for record in raw_records:
            if record.get("_pre_structured"):
                continue
            rec_url = record.get("url", "")
            if rec_url and rec_url.rstrip("/") != source_base_norm:
                subpage_urls.add(rec_url)
                subpage_urls.add(rec_url.rstrip("/"))

        # Log unique subpage URLs (without trailing-slash duplicates)
        unique_subpages = {u.rstrip("/") for u in subpage_urls}
        log.debug("[%s] Base URL: %s | %d cacheable subpage URLs identified",
                  source.source_id, source_base_url or "(none)", len(unique_subpages))

        for record in raw_records:
            is_subpage = False
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
                # A record is a subpage if its URL differs from the source's
                # configured base URL (i.e. it was discovered via deep crawl).
                record_url = record.get("url", "").rstrip("/")
                is_subpage = bool(source_base_url) and record_url != source_base_norm
                try:
                    extracted = await extract_events(record, is_subpage=is_subpage)
                except Exception as exc:
                    log.error("[%s] Extraction error for %s: %s", source.source_id, record.get("url", "?"), exc, exc_info=True)
                    errored_urls.add(record.get("url", ""))
                    continue

                # If Gemini was needed but failed, don't cache this URL
                # (regex fallback may have missed events)
                if record.get("_gemini_failed"):
                    failed_url = record.get("url", "")
                    errored_urls.add(failed_url)
                    log.debug("[%s] Gemini failed for %s — URL excluded from cache", source.source_id, failed_url)
                elif is_subpage and len(extracted) >= 1:
                    # Subpage with at least 1 extracted event — cache it even if no food found
                    rec_url = record.get("url", "")
                    if rec_url:
                        successfully_scraped.add(rec_url)
                elif is_subpage:
                    log.debug("[%s] Subpage %s returned 0 events — not caching", source.source_id, record.get("url", "?"))

            log.debug("[%s] Extracted %d events from %s", source.source_id, len(extracted), record.get("url", "?"))

            for event in extracted:
                event_url = _normalize_url(event.get("url", ""), source.source_id)

                # Skip events whose URL was already scraped in a previous run
                if event_url and visited_urls.is_visited(event_url):
                    log.debug("[%s] Skipping visited URL: %s", source.source_id, event_url)
                    continue

                food_result = detect_food(event)
                # Only fall back to raw record content on subpages (one event
                # per page).  On listing pages the raw content mixes many
                # events together, causing false-positive food matches.
                if not food_result and is_subpage:
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

                # Keyword scoring only (Gemini reviews in batch later)
                kw_result = _keyword_score(event, record)

                final = {
                    "id": make_event_id(source.source_id, title, date),
                    "source": source.source_id,
                    "title": title or "Untitled Event",
                    "date": date,
                    "start_time": event.get("start_time"),
                    "end_time": event.get("end_time"),
                    "location": event.get("location"),
                    "description": event.get("description", ""),
                    "url": event_url,
                    "food_type": food_result["food_type"],
                    "refreshments": food_result["refreshments"],
                    "refreshment_details": food_result["refreshment_details"],
                    "easeOfEntry": kw_result["score"],
                    "easeOfEntry_method": "keyword",
                    # Temporary fields for Gemini batch review
                    "_kw_ease_score": kw_result["score"],
                    "_kw_ease_signals": kw_result["signals"],
                    # Track if this event came from a pre-structured API record
                    "_pre_structured": bool(record.get("_pre_structured")),
                    "scraped_at": now,
                }
                events.append(final)

                log.debug("[%s] + %s (%s) — %s, kw_ease=%s",
                          source.source_id, title, date,
                          food_result["food_type"],
                          f"{kw_result['score']:.2f}" if kw_result["score"] is not None else "N/A")

        # Cache URLs that were successfully scraped:
        # 1. Subpage URLs scraped without error (even if 0 food events found)
        # 2. Event URLs from food events that match a subpage or API record
        # Never cache: base/listing URLs, errored URLs, hallucinated URLs
        cacheable: set[str] = set()
        skipped_errored: set[str] = set()
        skipped_not_subpage: set[str] = set()

        # Add all successfully scraped subpage URLs (regardless of food result)
        for u in successfully_scraped:
            if u not in errored_urls:
                cacheable.add(u)

        # Add event URLs from food events
        for e in events:
            u = e.get("url", "")
            if not u:
                continue
            if u in errored_urls:
                skipped_errored.add(u)
                continue
            if e.get("_pre_structured"):
                cacheable.add(u)
            elif u in subpage_urls or u.rstrip("/") in subpage_urls:
                cacheable.add(u)
            else:
                skipped_not_subpage.add(u)

        if cacheable:
            visited_urls.add_batch(list(cacheable))
        log.info("[%s] Visited URL cache: %d cached, %d skipped (errored), %d skipped (base/listing)",
                 source.source_id, len(cacheable), len(skipped_errored), len(skipped_not_subpage))
        for u in sorted(cacheable):
            log.debug("[%s]   cached: %s", source.source_id, u)
        for u in sorted(skipped_errored):
            log.debug("[%s]   not cached (error): %s", source.source_id, u)
        for u in sorted(skipped_not_subpage):
            log.debug("[%s]   not cached (base/listing): %s", source.source_id, u)

        log.info("[%s] Found %d food events", source.source_id, len(events))
        progress.source_done(source.source_id, len(events))
        return events
    except Exception as exc:
        log.error("[%s] Unexpected error: %s", source.source_id, exc, exc_info=True)
        progress.source_done(source.source_id, 0, error=True)
        return []


def _keyword_score(
    event: dict[str, Any],
    raw_record: dict[str, Any],
) -> dict[str, Any]:
    """Run keyword-based ease-of-entry scoring (fast, no API call)."""
    fragments = extract_text_fragments(event)
    fragments.extend(extract_text_fragments(raw_record))
    corpus = build_search_corpus(fragments)

    return keyword_scorer.score_ease_of_entry(
        corpus,
        price=raw_record.get("price"),
        spots=raw_record.get("spots"),
    )


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
