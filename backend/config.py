"""Load and instantiate source adapters from sources.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .logging_config import get_logger
from .sources.base import BaseSource
from .sources.crawl4ai_source import Crawl4aiSource
from .sources.amiv_api_source import AmivApiSource
from .sources.eventbrite_source import EventbriteSource

log = get_logger("aperowo.config")

_ADAPTER_MAP: dict[str, type[BaseSource]] = {
    "crawl4ai": Crawl4aiSource,
    "api": AmivApiSource,
    "amiv_api": AmivApiSource,
    "eventbrite": EventbriteSource,
}

SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"


def load_sources(path: Path | None = None) -> list[BaseSource]:
    """Load source configurations and return instantiated adapters."""
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
