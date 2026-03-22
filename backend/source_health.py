"""Source health monitoring.

Scans pipeline logs and events data to produce a per-source health report
written to data/source_health.json.  Used by the PM agent to detect broken
or degraded sources.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
SOURCES_FILE = Path(__file__).resolve().parent / "sources.json"
EVENTS_FILE = DATA_DIR / "events.json"
OUTPUT_FILE = DATA_DIR / "source_health.json"

# Log line patterns (plain-text format from logging_config)
_RE_FETCHING = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+INFO\s+\[aperowo\.pipeline\]\s+"
    r"\[(?P<src>[^\]]+)\] Fetching\.\.\."
)
_RE_FOUND = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+INFO\s+\[aperowo\.pipeline\]\s+"
    r"\[(?P<src>[^\]]+)\] Found (?P<n>\d+) food events"
)
_RE_ERROR_FETCH = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+ERROR\s+\[aperowo\.pipeline\]\s+"
    r"\[(?P<src>[^\]]+)\] Error fetching: (?P<msg>.+)"
)
_RE_ERROR_UNEXPECTED = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+ERROR\s+\[aperowo\.pipeline\]\s+"
    r"\[(?P<src>[^\]]+)\] Unexpected error: (?P<msg>.+)"
)


def get_latest_log(logs_dir: Path | None = None) -> Path | None:
    """Return the most recent pipeline log file, or None."""
    logs_dir = logs_dir or LOGS_DIR
    if not logs_dir.is_dir():
        return None
    logs = sorted(logs_dir.glob("pipeline_*.log"))
    return logs[-1] if logs else None


def parse_log(log_path: Path) -> dict[str, dict[str, Any]]:
    """Parse a pipeline log file and return per-source status dicts.

    Returns a mapping of source_id -> {
        "status": "ok" | "error" | "no_events",
        "events_found": int,
        "error_message": str | None,
        "fetch_started_at": str | None,
        "completed_at": str | None,
    }
    """
    results: dict[str, dict[str, Any]] = {}

    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            m = _RE_FETCHING.match(line)
            if m:
                src = m.group("src")
                results.setdefault(src, _empty_result())
                results[src]["fetch_started_at"] = m.group("ts")
                continue

            m = _RE_FOUND.match(line)
            if m:
                src = m.group("src")
                n = int(m.group("n"))
                results.setdefault(src, _empty_result())
                results[src]["completed_at"] = m.group("ts")
                results[src]["events_found"] = n
                results[src]["status"] = "ok" if n > 0 else "no_events"
                continue

            m = _RE_ERROR_FETCH.match(line)
            if m:
                src = m.group("src")
                results.setdefault(src, _empty_result())
                results[src]["status"] = "error"
                results[src]["error_message"] = m.group("msg").strip()
                results[src]["completed_at"] = m.group("ts")
                continue

            m = _RE_ERROR_UNEXPECTED.match(line)
            if m:
                src = m.group("src")
                results.setdefault(src, _empty_result())
                results[src]["status"] = "error"
                results[src]["error_message"] = m.group("msg").strip()
                results[src]["completed_at"] = m.group("ts")
                continue

    return results


def count_events_per_source(events_path: Path | None = None) -> dict[str, int]:
    """Count events per source in events.json."""
    events_path = events_path or EVENTS_FILE
    if not events_path.exists():
        return {}
    with events_path.open("r", encoding="utf-8") as f:
        events = json.load(f)
    counts: dict[str, int] = {}
    for event in events:
        src = event.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1
    return counts


def load_source_ids(sources_path: Path | None = None) -> list[dict[str, str]]:
    """Load source id and label from sources.json."""
    sources_path = sources_path or SOURCES_FILE
    with sources_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    sources_list = data.get("sources", data) if isinstance(data, dict) else data
    return [{"id": s["id"], "label": s.get("label", s["id"])} for s in sources_list]


def generate_health_report(
    sources_path: Path | None = None,
    events_path: Path | None = None,
    logs_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate the full source health report.

    Returns a dict suitable for writing to data/source_health.json.
    """
    source_infos = load_source_ids(sources_path)
    event_counts = count_events_per_source(events_path)
    log_path = get_latest_log(logs_dir)

    log_results: dict[str, dict[str, Any]] = {}
    log_file_name: str | None = None
    if log_path:
        log_results = parse_log(log_path)
        log_file_name = log_path.name

    sources_report: list[dict[str, Any]] = []
    healthy = 0
    errored = 0
    no_events = 0
    missing = 0

    for info in source_infos:
        sid = info["id"]
        log_data = log_results.get(sid)
        total_events = event_counts.get(sid, 0)

        if log_data:
            status = log_data["status"]
        else:
            status = "missing"

        entry: dict[str, Any] = {
            "id": sid,
            "label": info["label"],
            "status": status,
            "total_events_in_data": total_events,
        }
        if log_data:
            entry["last_run_events"] = log_data["events_found"]
            entry["fetch_started_at"] = log_data["fetch_started_at"]
            entry["completed_at"] = log_data["completed_at"]
            if log_data["error_message"]:
                entry["error_message"] = log_data["error_message"]

        if status == "ok":
            healthy += 1
        elif status == "error":
            errored += 1
        elif status == "no_events":
            no_events += 1
        else:
            missing += 1

        sources_report.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "log_file": log_file_name,
        "summary": {
            "total_sources": len(source_infos),
            "healthy": healthy,
            "errored": errored,
            "no_events": no_events,
            "missing_from_log": missing,
        },
        "sources": sources_report,
    }


def write_health_report(
    output_path: Path | None = None,
    **kwargs: Any,
) -> Path:
    """Generate and write data/source_health.json. Returns the output path."""
    output_path = output_path or OUTPUT_FILE
    report = generate_health_report(**kwargs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return output_path


def _empty_result() -> dict[str, Any]:
    return {
        "status": "missing",
        "events_found": 0,
        "error_message": None,
        "fetch_started_at": None,
        "completed_at": None,
    }


if __name__ == "__main__":
    path = write_health_report()
    with path.open() as f:
        report = json.load(f)
    s = report["summary"]
    print(
        f"Source health report written to {path}\n"
        f"  {s['total_sources']} sources: "
        f"{s['healthy']} healthy, {s['errored']} errored, "
        f"{s['no_events']} no_events, {s['missing_from_log']} missing"
    )
