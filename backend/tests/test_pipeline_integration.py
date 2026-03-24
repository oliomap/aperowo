"""Integration tests for the full pipeline dry-run.

These tests exercise the pipeline orchestrator end-to-end with mock sources,
ensuring that fetching → extraction → food detection → scoring → dedup → output
all work together.  Heavy optional dependencies (crawl4ai, google-genai) are
stubbed via ``conftest.py`` so they are **not** required at test time.

The tests inject lightweight MockSource adapters via the ``_ADAPTER_MAP``
mechanism in ``backend.config``.
"""

import asyncio
import json

import pytest

import backend.config
import backend.pipeline
import backend.visited_urls
import backend.filtering.gemini_validator as _gv


# ---------------------------------------------------------------------------
# Mock source adapters
# ---------------------------------------------------------------------------

class MockSource:
    """Minimal source adapter that returns a single food event."""

    def __init__(self, source_id: str, config: dict):
        self.source_id = source_id
        self.config = config

    async def fetch_raw(self) -> list[dict]:
        return [
            {
                "title": "Free Pizza at CAB",
                "description": (
                    "Come join us for free pizza and drinks at CAB G11. "
                    "Everyone is welcome — no registration needed."
                ),
                "url": "https://example.com/pizza",
                "date": "2026-03-22",
                "location": "CAB G11",
                "_pre_structured": True,
            }
        ]


class MockSourceMultiple:
    """Source adapter returning several events (some with food, some without)."""

    def __init__(self, source_id: str, config: dict):
        self.source_id = source_id
        self.config = config

    async def fetch_raw(self) -> list[dict]:
        return [
            {
                "title": "Free Pizza at CAB",
                "description": "Free pizza for everyone at CAB G11.",
                "url": "https://example.com/pizza",
                "date": "2026-03-22",
                "location": "CAB G11",
                "_pre_structured": True,
            },
            {
                "title": "Beer and Snacks Social",
                "description": "Come enjoy free beer, snacks and great company.",
                "url": "https://example.com/beer",
                "date": "2026-03-23",
                "location": "HG E5",
                "_pre_structured": True,
            },
            {
                "title": "Quantum Physics Lecture",
                "description": "A lecture on quantum entanglement.",
                "url": "https://example.com/physics",
                "date": "2026-03-24",
                "location": "ML H44",
                "_pre_structured": True,
            },
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pipeline_env(tmp_path, monkeypatch):
    """Set up an isolated pipeline environment with mocked heavy deps."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    events_file = data_dir / "events.json"

    sources_file = tmp_path / "sources.json"
    sources_file.write_text(json.dumps([
        {"id": "mock", "type": "mock", "config": {"url": "https://example.com"}}
    ]))

    # Inject mock adapter — prevents load_sources from lazy-importing real adapters
    monkeypatch.setattr(backend.config, "_ADAPTER_MAP", {"mock": MockSource})
    monkeypatch.setattr(backend.config, "SOURCES_FILE", sources_file)

    # Patch pipeline output path
    monkeypatch.setattr(backend.pipeline, "OUTPUT_FILE", events_file)

    # Patch visited_urls so nothing is skipped
    monkeypatch.setattr(backend.visited_urls, "is_visited", lambda url: False)
    monkeypatch.setattr(backend.visited_urls, "load", lambda: None)
    monkeypatch.setattr(backend.visited_urls, "add_batch", lambda urls: None)

    # Mock Gemini validator — pass events through with a synthetic score.
    # Must patch on both the validator module AND the pipeline module (which
    # imported the function directly via ``from … import``).
    monkeypatch.setattr(_gv, "is_available", lambda: True)

    async def mock_validate(events, **kw):
        for e in events:
            e["easeOfEntry"] = 0.9
            e["easeOfEntry_method"] = "gemini"
        return events

    monkeypatch.setattr(_gv, "validate_and_score_events", mock_validate)
    monkeypatch.setattr(backend.pipeline, "validate_and_score_events", mock_validate)

    return {
        "events_file": events_file,
        "sources_file": sources_file,
        "data_dir": data_dir,
        "tmp_path": tmp_path,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine from a sync test."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """End-to-end pipeline tests with mock sources."""

    def test_pipeline_produces_events(self, pipeline_env):
        """The pipeline should write at least one food event to events.json."""
        events_file = pipeline_env["events_file"]
        result = _run(backend.pipeline.run(output_path=events_file))

        assert events_file.exists(), "events.json was not created"
        with events_file.open() as f:
            written = json.load(f)

        assert len(written) > 0, "No events written"
        assert len(result) == len(written)

    def test_pipeline_event_fields(self, pipeline_env):
        """Every event should carry the required fields after processing."""
        events_file = pipeline_env["events_file"]
        _run(backend.pipeline.run(output_path=events_file))

        with events_file.open() as f:
            events = json.load(f)

        required_fields = {
            "id", "source", "title", "date", "url",
            "food_type", "easeOfEntry",
        }
        for event in events:
            missing = required_fields - set(event.keys())
            assert not missing, (
                f"Event missing fields {missing}: {event.get('title')}"
            )

    def test_pipeline_food_detection(self, pipeline_env):
        """The mock 'pizza' event should be detected as a food event."""
        events_file = pipeline_env["events_file"]
        _run(backend.pipeline.run(output_path=events_file))

        with events_file.open() as f:
            events = json.load(f)

        titles = [e["title"] for e in events]
        assert "Free Pizza at CAB" in titles
        pizza_event = next(e for e in events if e["title"] == "Free Pizza at CAB")
        assert pizza_event["food_type"], (
            "food_type should be non-empty for pizza event"
        )

    def test_pipeline_filters_non_food(self, pipeline_env, monkeypatch):
        """Events without food keywords should be filtered out."""
        monkeypatch.setattr(
            backend.config, "_ADAPTER_MAP", {"mock": MockSourceMultiple}
        )

        events_file = pipeline_env["events_file"]
        _run(backend.pipeline.run(output_path=events_file))

        with events_file.open() as f:
            events = json.load(f)

        titles = [e["title"] for e in events]
        assert "Quantum Physics Lecture" not in titles, (
            "Non-food event should be filtered out"
        )
        assert any("Pizza" in t for t in titles)

    def test_pipeline_deduplication(self, pipeline_env, monkeypatch):
        """Duplicate events from different sources should be deduped."""
        sources_file = pipeline_env["sources_file"]
        sources_file.write_text(json.dumps([
            {"id": "mock-a", "type": "mock", "config": {"url": "https://a.example.com"}},
            {"id": "mock-b", "type": "mock", "config": {"url": "https://b.example.com"}},
        ]))

        events_file = pipeline_env["events_file"]
        _run(backend.pipeline.run(output_path=events_file))

        with events_file.open() as f:
            events = json.load(f)

        pizza_events = [e for e in events if "Pizza" in e.get("title", "")]
        assert len(pizza_events) == 1, (
            f"Expected 1 pizza event after dedup, got {len(pizza_events)}"
        )

    def test_pipeline_empty_source(self, pipeline_env, monkeypatch):
        """Pipeline should handle a source returning zero records."""

        class EmptySource:
            def __init__(self, source_id, config):
                self.source_id = source_id
                self.config = config

            async def fetch_raw(self):
                return []

        monkeypatch.setattr(
            backend.config, "_ADAPTER_MAP", {"mock": EmptySource}
        )

        events_file = pipeline_env["events_file"]
        result = _run(backend.pipeline.run(output_path=events_file))

        assert events_file.exists()
        with events_file.open() as f:
            events = json.load(f)

        assert events == []
        assert result == []

    def test_pipeline_merge_preserves_existing(self, pipeline_env):
        """Existing events.json entries should be preserved after merge."""
        events_file = pipeline_env["events_file"]

        existing = [
            {
                "id": "old-source-old-event-2026-01-01",
                "source": "old-source",
                "title": "Old Cake Event",
                "date": "2026-01-01",
                "url": "https://old.example.com/cake",
                "food_type": "cake",
                "refreshments": True,
                "refreshment_details": "cake",
                "easeOfEntry": 0.8,
                "easeOfEntry_method": "keyword",
                "location": "HG E3",
                "scraped_at": "2026-01-01T00:00:00Z",
            }
        ]
        with events_file.open("w") as f:
            json.dump(existing, f)

        _run(backend.pipeline.run(output_path=events_file))

        with events_file.open() as f:
            merged = json.load(f)

        titles = [e["title"] for e in merged]
        assert "Old Cake Event" in titles, "Existing event should be preserved"
        assert "Free Pizza at CAB" in titles, "New event should be added"

    def test_pipeline_source_error_resilience(self, pipeline_env, monkeypatch):
        """Pipeline should continue if one source raises an exception."""

        class FailingSource:
            def __init__(self, source_id, config):
                self.source_id = source_id
                self.config = config

            async def fetch_raw(self):
                raise RuntimeError("Network timeout")

        sources_file = pipeline_env["sources_file"]
        sources_file.write_text(json.dumps([
            {"id": "failing", "type": "fail", "config": {"url": "https://fail.example.com"}},
            {"id": "mock", "type": "mock", "config": {"url": "https://example.com"}},
        ]))
        monkeypatch.setattr(
            backend.config, "_ADAPTER_MAP",
            {"fail": FailingSource, "mock": MockSource},
        )

        events_file = pipeline_env["events_file"]
        result = _run(backend.pipeline.run(output_path=events_file))

        assert len(result) > 0, "Working source should still produce events"
