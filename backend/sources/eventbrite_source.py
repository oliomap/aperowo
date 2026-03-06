"""Eventbrite source adapter.

Scrapes the ETH Zurich Eventbrite organizer page for free events.
Uses crawl4ai to render the JS-heavy Eventbrite pages.
"""

from __future__ import annotations

from typing import Any

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

from .base import BaseSource
from ..logging_config import get_logger

log = get_logger("aperowo.sources.eventbrite")


class EventbriteSource(BaseSource):
    """Scrape events from an Eventbrite organizer page."""

    async def fetch_raw(self) -> list[dict[str, Any]]:
        url = self.config.get(
            "url",
            "https://www.eventbrite.com/o/eth-zurich-25205217049",
        )

        config = CrawlerRunConfig(
            scraping_strategy=LXMLWebScrapingStrategy(),
            verbose=False,
            excluded_tags=["header", "footer", "nav", "aside"],
        )

        browser_config = BrowserConfig(
            headless=True,
            java_script_enabled=True,
        )

        records: list[dict[str, Any]] = []
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url, config=config)

            if not isinstance(result, list):
                result = [result]

            for r in result:
                if not r.success:
                    log.warning("[%s] Failed to crawl Eventbrite: %s", self.source_id, r.url)
                    continue
                records.append({
                    "url": r.url,
                    "markdown": r.markdown,
                    "html": r.html,
                    "fit_html": r.fit_html,
                    "extracted_content": r.extracted_content,
                    "metadata": r.metadata or {},
                })

        log.info("[%s] Crawled %d Eventbrite pages", self.source_id, len(records))
        return records
