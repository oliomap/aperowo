"""Visited URLs cache — tracks event URLs that have already been scraped.

Stores exact event URLs (not base/source URLs) in a JSON file so they can
be skipped on subsequent pipeline runs. The cache is updated continuously
as the crawler discovers new event URLs.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .logging_config import get_logger

log = get_logger("aperowo.visited_urls")

_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "visited_urls.json"

# In-memory set + lock for thread-safe access from async tasks
_visited: set[str] = set()
_lock = threading.Lock()
_loaded = False


def load(path: Path | None = None) -> int:
    """Load visited URLs from disk into memory. Returns count loaded."""
    global _loaded
    cache_path = path or _CACHE_FILE

    with _lock:
        _visited.clear()
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    _visited.update(url for url in data if isinstance(url, str))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Could not load visited URLs cache: %s", exc)

        _loaded = True
        count = len(_visited)
        log.info("Loaded %d visited URLs from cache", count)
        return count


def is_visited(url: str) -> bool:
    """Check if a URL has already been visited."""
    if not url:
        return False
    with _lock:
        return url in _visited


def add(url: str, *, persist: bool = True, path: Path | None = None) -> None:
    """Mark a URL as visited and optionally persist to disk."""
    if not url:
        return
    with _lock:
        if url in _visited:
            return
        _visited.add(url)
    if persist:
        save(path)


def add_batch(urls: list[str], *, path: Path | None = None) -> None:
    """Mark multiple URLs as visited and persist once."""
    new_urls = [u for u in urls if u]
    if not new_urls:
        return
    with _lock:
        before = len(_visited)
        _visited.update(new_urls)
        after = len(_visited)
    actually_new = after - before
    log.debug("add_batch: %d URLs provided, %d new, %d total in cache", len(new_urls), actually_new, after)
    save(path)


def save(path: Path | None = None) -> None:
    """Persist the current visited set to disk."""
    cache_path = path or _CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        urls = sorted(_visited)
    try:
        cache_path.write_text(
            json.dumps(urls, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        log.debug("Saved %d visited URLs to %s", len(urls), cache_path)
    except OSError as exc:
        log.warning("Could not save visited URLs cache: %s", exc)


def clear(*, path: Path | None = None) -> None:
    """Clear all visited URLs (both in-memory and on disk)."""
    cache_path = path or _CACHE_FILE
    with _lock:
        _visited.clear()
    if cache_path.exists():
        cache_path.unlink()
    log.info("Visited URLs cache cleared")


def count() -> int:
    """Return the number of visited URLs."""
    with _lock:
        return len(_visited)
