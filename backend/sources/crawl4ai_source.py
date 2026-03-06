"""Generic crawl4ai-based source adapter.

Uses AsyncWebCrawler (Playwright-backed) to render JavaScript-heavy pages
and extract markdown/HTML content.
"""

from __future__ import annotations

from typing import Any

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain

from .base import BaseSource
from ..logging_config import get_logger

log = get_logger("aperowo.sources.crawl4ai")


class Crawl4aiSource(BaseSource):
    """Crawl a website using crawl4ai with Playwright browser rendering."""

    async def fetch_raw(self) -> list[dict[str, Any]]:
        url = self.config["url"]
        depth = self.config.get("depth", 1)
        include_patterns = self.config.get("include_patterns", [])
        exclude_patterns = self.config.get("exclude_patterns", [])

        # Build filter chain
        filters = []
        if include_patterns:
            if not isinstance(include_patterns, list):
                include_patterns = [include_patterns]
            filters.append(URLPatternFilter(patterns=include_patterns))
        if exclude_patterns:
            if not isinstance(exclude_patterns, list):
                exclude_patterns = [exclude_patterns]
            filters.append(URLPatternFilter(patterns=exclude_patterns, reverse=True))

        filter_chain = FilterChain(filters) if filters else None

        crawl_config_kwargs: dict[str, Any] = {
            "scraping_strategy": LXMLWebScrapingStrategy(),
            "verbose": False,
            "excluded_tags": ["header", "footer", "nav", "aside"],
        }

        if filter_chain:
            crawl_config_kwargs["deep_crawl_strategy"] = BFSDeepCrawlStrategy(
                max_depth=depth,
                filter_chain=filter_chain,
            )

        config = CrawlerRunConfig(**crawl_config_kwargs)

        browser_config = BrowserConfig(
            headless=True,
            java_script_enabled=True,
        )

        records: list[dict[str, Any]] = []
        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun(url, config=config)

            if not isinstance(results, list):
                results = [results]

            for result in results:
                if not result.success:
                    log.warning("[%s] Failed to crawl: %s", self.source_id, result.url)
                    continue
                records.append({
                    "url": result.url,
                    "markdown": result.markdown,
                    "html": result.html,
                    "fit_html": result.fit_html,
                    "extracted_content": result.extracted_content,
                    "metadata": result.metadata or {},
                })

        log.info("[%s] Crawled %d pages from %s", self.source_id, len(records), url)
        return records
