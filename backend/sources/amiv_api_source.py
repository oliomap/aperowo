"""AMIV REST API source adapter.

Fetches events from the AMIV API with pagination support.
Returns pre-structured event data (no crawl4ai needed).
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

import requests

from .base import BaseSource
from ..logging_config import get_logger
from .. import visited_urls

log = get_logger("aperowo.sources.amiv")


class AmivApiSource(BaseSource):
    """Fetch events from the AMIV REST API."""

    async def fetch_raw(self) -> list[dict[str, Any]]:
        base_url = self.config.get("base_url", "https://api.amiv.ethz.ch/events/")
        api_filter = self.config.get("filter")

        all_events = self._fetch_all_pages(base_url, api_filter)
        log.info("[%s] Fetched %d events from AMIV API", self.source_id, len(all_events))

        # Convert AMIV format to our extraction-ready format
        records = []
        for event in all_events:
            event_url = event.get("_links", {}).get("self", {}).get("href", "")
            if event_url and visited_urls.is_visited(event_url):
                log.debug("[%s] Skipping visited event: %s", self.source_id, event_url)
                continue
            records.append({
                "url": event_url,
                "title": event.get("title_en") or event.get("title_de", ""),
                "date": (event.get("time_start", "") or "")[:10],
                "start_time": self._extract_time(event.get("time_start")),
                "end_time": self._extract_time(event.get("time_end")),
                "location": event.get("location", ""),
                "description": event.get("description_en") or event.get("description_de", ""),
                "price": event.get("price"),
                "spots": event.get("spots"),
                # Mark as pre-structured so extractor skips re-extraction
                "_pre_structured": True,
                # Keep full text for food detection
                "markdown": " ".join(filter(None, [
                    event.get("title_en", ""),
                    event.get("title_de", ""),
                    event.get("description_en", ""),
                    event.get("description_de", ""),
                    event.get("catchphrase_en", ""),
                    event.get("catchphrase_de", ""),
                ])),
            })

        return records

    def _fetch_all_pages(
        self, base_url: str, filter_dict: dict | None
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        if filter_dict:
            query = urllib.parse.urlencode({"where": json.dumps(filter_dict)})
            url: str | None = f"{base_url}?{query}"
        else:
            url = base_url

        while url:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "_items" in data:
                events.extend(data["_items"])
                next_href = data.get("_links", {}).get("next", {}).get("href")
                if next_href and not next_href.startswith("http"):
                    url = requests.compat.urljoin(base_url.rstrip("/"), next_href)
                else:
                    url = next_href
            elif isinstance(data, list):
                events.extend(data)
                url = None
            else:
                url = None

        return events

    @staticmethod
    def _extract_time(iso_string: str | None) -> str | None:
        if not iso_string or len(iso_string) < 16:
            return None
        return iso_string[11:16]
