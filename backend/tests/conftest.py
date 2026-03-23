"""Shared test fixtures and module-level mocks for the test suite.

Heavy optional dependencies (crawl4ai, google-genai) are stubbed out in
``sys.modules`` so that test collection and imports succeed in minimal CI
environments that only have the core Python packages installed.

This file is loaded by pytest *before* any test module is imported, so the
stubs are in place before the import chain reaches crawl4ai or google.genai.
"""

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out heavy optional dependencies that are not needed for unit / integration
# tests.  The stubs must be registered *before* any ``import backend.…`` that
# would transitively pull them in.
# ---------------------------------------------------------------------------

def _install_stub(name: str, parent_mock: MagicMock | None = None) -> MagicMock:
    """Register a MagicMock in sys.modules if the real package is absent."""
    if name in sys.modules and not isinstance(sys.modules[name], MagicMock):
        return sys.modules[name]  # Real package is installed — leave it alone.
    mock = getattr(parent_mock, name.rsplit(".", 1)[-1]) if parent_mock else MagicMock()
    sys.modules.setdefault(name, mock)
    return mock


# google.genai (used by gemini_extractor, gemini_validator, gemini_rate_limit)
_google = _install_stub("google")
_genai = _install_stub("google.genai", _google)
_install_stub("google.genai.errors", _genai)

# crawl4ai (used by crawl4ai_source, eventbrite_source)
_crawl4ai = _install_stub("crawl4ai")
_install_stub("crawl4ai.content_scraping_strategy", _crawl4ai)
_deep = _install_stub("crawl4ai.deep_crawling", _crawl4ai)
_install_stub("crawl4ai.deep_crawling.filters", _deep)
