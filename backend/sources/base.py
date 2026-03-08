"""Abstract base class for event source adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSource(ABC):
    """Base class that all source adapters must implement.

    Each adapter fetches raw page/event data from a specific source type
    and returns it in a list of dictionaries that the extraction layer
    can process.
    """

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config

    @abstractmethod
    async def fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch raw data from the source.

        For crawl sources: returns list of crawled page records with
        'url', 'markdown', 'html', 'metadata', etc.

        For API sources: returns list of structured event dicts.
        """
        ...

    @property
    def source_type(self) -> str:
        return self.config.get("type", "unknown")
