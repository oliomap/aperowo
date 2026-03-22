"""Tests for backend.source_health — log parsing, event counting, report generation."""

import json

import pytest

from backend.source_health import (
    count_events_per_source,
    generate_health_report,
    get_latest_log,
    load_source_ids,
    parse_log,
    write_health_report,
)


# ---------------------------------------------------------------------------
# get_latest_log
# ---------------------------------------------------------------------------

class TestGetLatestLog:
    def test_returns_none_for_missing_dir(self, tmp_path):
        assert get_latest_log(tmp_path / "nonexistent") is None

    def test_returns_none_for_empty_dir(self, tmp_path):
        assert get_latest_log(tmp_path) is None

    def test_returns_latest_log(self, tmp_path):
        (tmp_path / "pipeline_2026-03-01_08-00-00.log").write_text("old")
        (tmp_path / "pipeline_2026-03-06_09-00-00.log").write_text("new")
        (tmp_path / "other.txt").write_text("ignore")
        result = get_latest_log(tmp_path)
        assert result is not None
        assert result.name == "pipeline_2026-03-06_09-00-00.log"


# ---------------------------------------------------------------------------
# parse_log
# ---------------------------------------------------------------------------

_SAMPLE_LOG = """\
2026-03-06 09:08:21  INFO      [aperowo.pipeline]  Pipeline: processing 3 sources concurrently (max 5)...
2026-03-06 09:08:21  INFO      [aperowo.pipeline]  [amiv] Fetching...
2026-03-06 09:08:49  INFO      [aperowo.pipeline]  [amiv] Found 5 food events
2026-03-06 09:08:49  INFO      [aperowo.pipeline]  [vseth] Fetching...
2026-03-06 09:09:13  INFO      [aperowo.pipeline]  [vseth] Found 0 food events
2026-03-06 09:08:49  INFO      [aperowo.pipeline]  [broken] Fetching...
2026-03-06 09:08:55  ERROR     [aperowo.pipeline]  [broken] Error fetching: ConnectionError: timeout
"""


class TestParseLog:
    @pytest.fixture()
    def log_file(self, tmp_path):
        p = tmp_path / "pipeline_test.log"
        p.write_text(_SAMPLE_LOG)
        return p

    def test_parses_successful_source(self, log_file):
        results = parse_log(log_file)
        assert results["amiv"]["status"] == "ok"
        assert results["amiv"]["events_found"] == 5
        assert results["amiv"]["fetch_started_at"] == "2026-03-06 09:08:21"
        assert results["amiv"]["completed_at"] == "2026-03-06 09:08:49"

    def test_parses_no_events_source(self, log_file):
        results = parse_log(log_file)
        assert results["vseth"]["status"] == "no_events"
        assert results["vseth"]["events_found"] == 0

    def test_parses_error_source(self, log_file):
        results = parse_log(log_file)
        assert results["broken"]["status"] == "error"
        assert "ConnectionError" in results["broken"]["error_message"]

    def test_unexpected_error(self, tmp_path):
        log = tmp_path / "pipeline_test.log"
        log.write_text(
            "2026-03-06 09:10:00  ERROR     [aperowo.pipeline]  "
            "[badone] Unexpected error: RuntimeError: boom\n"
        )
        results = parse_log(log)
        assert results["badone"]["status"] == "error"
        assert "RuntimeError" in results["badone"]["error_message"]

    def test_empty_log(self, tmp_path):
        log = tmp_path / "pipeline_test.log"
        log.write_text("")
        assert parse_log(log) == {}


# ---------------------------------------------------------------------------
# count_events_per_source
# ---------------------------------------------------------------------------

class TestCountEventsPerSource:
    def test_counts_correctly(self, tmp_path):
        events = [
            {"source": "amiv", "title": "A"},
            {"source": "amiv", "title": "B"},
            {"source": "vseth", "title": "C"},
        ]
        p = tmp_path / "events.json"
        p.write_text(json.dumps(events))
        counts = count_events_per_source(p)
        assert counts == {"amiv": 2, "vseth": 1}

    def test_missing_file(self, tmp_path):
        assert count_events_per_source(tmp_path / "nope.json") == {}

    def test_empty_list(self, tmp_path):
        p = tmp_path / "events.json"
        p.write_text("[]")
        assert count_events_per_source(p) == {}


# ---------------------------------------------------------------------------
# load_source_ids
# ---------------------------------------------------------------------------

class TestLoadSourceIds:
    def test_loads_sources(self, tmp_path):
        sources = {"sources": [
            {"id": "a", "label": "Alpha", "type": "crawl4ai", "config": {}},
            {"id": "b", "type": "api", "config": {}},
        ]}
        p = tmp_path / "sources.json"
        p.write_text(json.dumps(sources))
        result = load_source_ids(p)
        assert result == [
            {"id": "a", "label": "Alpha"},
            {"id": "b", "label": "b"},
        ]


# ---------------------------------------------------------------------------
# generate_health_report
# ---------------------------------------------------------------------------

class TestGenerateHealthReport:
    @pytest.fixture()
    def setup(self, tmp_path):
        # sources.json
        sources = {"sources": [
            {"id": "amiv", "label": "AMIV", "type": "api", "config": {}},
            {"id": "vseth", "label": "VSETH", "type": "crawl4ai", "config": {}},
            {"id": "ghost", "label": "Ghost", "type": "crawl4ai", "config": {}},
        ]}
        sources_path = tmp_path / "sources.json"
        sources_path.write_text(json.dumps(sources))

        # events.json
        events = [
            {"source": "amiv", "title": "A"},
            {"source": "amiv", "title": "B"},
            {"source": "vseth", "title": "C"},
        ]
        events_path = tmp_path / "events.json"
        events_path.write_text(json.dumps(events))

        # log file
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log = logs_dir / "pipeline_2026-03-06_09-00-00.log"
        log.write_text(
            "2026-03-06 09:00:00  INFO      [aperowo.pipeline]  [amiv] Fetching...\n"
            "2026-03-06 09:00:05  INFO      [aperowo.pipeline]  [amiv] Found 2 food events\n"
            "2026-03-06 09:00:00  INFO      [aperowo.pipeline]  [vseth] Fetching...\n"
            "2026-03-06 09:00:10  INFO      [aperowo.pipeline]  [vseth] Found 1 food events\n"
        )

        return {
            "sources_path": sources_path,
            "events_path": events_path,
            "logs_dir": logs_dir,
        }

    def test_report_structure(self, setup):
        report = generate_health_report(**setup)
        assert "generated_at" in report
        assert "summary" in report
        assert "sources" in report
        assert report["log_file"] == "pipeline_2026-03-06_09-00-00.log"

    def test_summary_counts(self, setup):
        report = generate_health_report(**setup)
        s = report["summary"]
        assert s["total_sources"] == 3
        assert s["healthy"] == 2
        assert s["errored"] == 0
        assert s["no_events"] == 0
        assert s["missing_from_log"] == 1  # ghost

    def test_source_details(self, setup):
        report = generate_health_report(**setup)
        by_id = {s["id"]: s for s in report["sources"]}

        assert by_id["amiv"]["status"] == "ok"
        assert by_id["amiv"]["total_events_in_data"] == 2
        assert by_id["amiv"]["last_run_events"] == 2

        assert by_id["ghost"]["status"] == "missing"
        assert by_id["ghost"]["total_events_in_data"] == 0

    def test_no_logs_dir(self, setup):
        setup["logs_dir"] = setup["logs_dir"].parent / "nope"
        report = generate_health_report(**setup)
        assert report["log_file"] is None
        assert all(s["status"] == "missing" for s in report["sources"])


# ---------------------------------------------------------------------------
# write_health_report
# ---------------------------------------------------------------------------

class TestWriteHealthReport:
    def test_writes_valid_json(self, tmp_path):
        sources = {"sources": [{"id": "x", "label": "X", "type": "api", "config": {}}]}
        sp = tmp_path / "sources.json"
        sp.write_text(json.dumps(sources))
        ep = tmp_path / "events.json"
        ep.write_text("[]")

        out = tmp_path / "health.json"
        result = write_health_report(
            output_path=out,
            sources_path=sp,
            events_path=ep,
            logs_dir=tmp_path / "nologs",
        )
        assert result == out
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["summary"]["total_sources"] == 1
