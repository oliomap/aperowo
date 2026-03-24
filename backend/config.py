"""Load and instantiate source adapters from sources.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .sources.base import BaseSource

log = get_logger("aperowo.config")


def _get_adapter_map() -> dict[str, type[BaseSource]]:
    """Lazily import source adapters so optional deps (crawl4ai) aren't
    required at module-import time.  This allows tests to monkeypatch
    _ADAPTER_MAP without triggering heavy dependency imports."""
    from .sources.crawl4ai_source import Crawl4aiSource
    from .sources.amiv_api_source import AmivApiSource
    from .sources.eventbrite_source import EventbriteSource

    return {
        "crawl4ai": Crawl4aiSource,
        "api": AmivApiSource,
        "amiv_api": AmivApiSource,
        "eventbrite": EventbriteSource,
    }


# Mutable mapping so tests can monkeypatch entries without importing adapters.
_ADAPTER_MAP: dict[str, type[BaseSource]] = {}

SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"


def load_sources(path: Path | None = None) -> list[BaseSource]:
    """Load source configurations and return instantiated adapters."""
    global _ADAPTER_MAP

    # Populate adapter map on first real call (lazy-loads crawl4ai etc.)
    # Tests can pre-populate _ADAPTER_MAP via monkeypatch to skip this.
    if not _ADAPTER_MAP:
        _ADAPTER_MAP = _get_adapter_map()

    path = path or SOURCES_FILE

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    sources_list = data.get("sources", data) if isinstance(data, dict) else data
    adapters: list[BaseSource] = []

    for entry in sources_list:
        source_id = entry["id"]
        source_type = entry.get("type", entry.get("adapter", "crawl4ai"))
        config = entry.get("config", {})
        config["type"] = source_type

        adapter_cls = _ADAPTER_MAP.get(source_type)
        if not adapter_cls:
            log.warning("Unknown source type '%s' for %s, skipping", source_type, source_id)
            continue

        adapters.append(adapter_cls(source_id, config))

    return adapters
