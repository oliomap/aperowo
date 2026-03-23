"""Integration tests for the full pipeline dry-run."""

import json
from pathlib import Path

import pytest

from backend.pipeline import run
from backend.config import load_sources


class MockSource:
    """Minimal mock source that returns a single food event."""
    def __init__(self, source_id, config):
        self.source_id = source_id
        self.config = config

    async def fetch_raw(self):
        """Mock fetching raw records."""
        return [
            {
                "title": "Free Pizza at CAB",
                "description": "Come join us for free pizza and drinks at CAB G11. This is a great event for everyone to enjoy pizza.",
                "url": "https://example.com/pizza",
                "date": "2026-03-22",
                "location": "CAB G11",
                "_pre_structured": True,
            }
        ]


@pytest.mark.asyncio
async def test_pipeline_dry_run(tmp_path, monkeypatch):
    """Run the pipeline with a mock source and verify events.json is written."""
    # Setup paths
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    events_file = data_dir / "events.json"
    
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps([
        {"id": "mock", "type": "mock", "config": {"url": "https://example.com/events"}}
    ]))

    # Monkeypatch to use our mock source
    from backend.config import _ADAPTER_MAP
    monkeypatch.setitem(_ADAPTER_MAP, "mock", MockSource)
    
    # Force Gemini to be "available" and return our mocked event
    import backend.filtering.gemini_validator
    monkeypatch.setattr(backend.filtering.gemini_validator, "is_available", lambda: True)

    async def mock_process_batch(events, **kwargs):
        # Just return the events as "valid"
        for e in events:
            e["easeOfEntry"] = 0.9
            e["easeOfEntry_method"] = "gemini"
        return events

    monkeypatch.setattr(backend.filtering.gemini_validator, "_process_batch", mock_process_batch)
    
    # Monkeypatch paths in pipeline and config
    import backend.pipeline
    import backend.config
    monkeypatch.setattr(backend.pipeline, "OUTPUT_FILE", events_file)
    monkeypatch.setattr(backend.config, "SOURCES_FILE", sources_file)

    # Run pipeline (async)
    # Use output_path parameter if available, otherwise reliance on OUTPUT_FILE monkeypatch
    import backend.visited_urls
    monkeypatch.setattr(backend.visited_urls, "is_visited", lambda url: False)
    
    await run(output_path=events_file)

    # Verify results
    assert events_file.exists()
    with events_file.open() as f:
        events = json.load(f)
    
    assert len(events) > 0
    assert events[0]["title"] == "Free Pizza at CAB"
    assert "pizza" in events[0]["food_type"].lower() or "refreshments" in events[0]
