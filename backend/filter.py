"""
Utilities for transforming pre-crawled event payloads into the structure the
calendar expects.

The functions in this module deliberately stay agnostic to the concrete source
format.  They operate on generic JSON-like dictionaries, reusing the refreshment
keyword configuration from :mod:`backend.amiv_api` so the filtering semantics
remain consistent across data sources.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any, Callable, Union
from thefuzz import fuzz



try:
    from .amiv_api import REFRESHMENT_DISPLAY_PRIORITY, REFRESHMENT_RULES, normalize_text
except ImportError:  # pragma: no cover - fallback for script execution
    from amiv_api import REFRESHMENT_DISPLAY_PRIORITY, REFRESHMENT_RULES, normalize_text


# Type alias used throughout the module.
JSONMapping = Mapping[str, Any]
JSONValue = Union[str, int, float, bool, None, Mapping[str, Any], Sequence[Any]]
FieldExtractor = Union[str, Callable[[JSONMapping], Any]]

# Default mapping used when exporting filtered events.  Each entry lists a set of
# candidate keys (with optional dotted accessors) that are attempted in order
# until a value is found.  The mapping is intentionally broad so other sources
# can plug into it without additional configuration.
DEFAULT_FIELD_MAPPING: Mapping[str, Sequence[FieldExtractor]] = {
    "url": ("url", "_links.self.href", "metadata.url"),
    "title": ("title", "name", "metadata.title"),
    # ``_extracted_date`` is a sentinel resolved by ``_resolve_field`` so the
    # function can fall back to the text-based parser defined in this module.
    "date": ("date", "metadata.date", "time_start", "_extracted_date"),
    "start_time": ("start_time", "metadata.start_time", "time_start", "_extracted_start_time"),
    "end_time": ("end_time", "metadata.end_time", "time_end", "_extracted_end_time"),
    "location": ("location", "metadata.location", "venue"),
}

_MONTH_VARIANTS: Mapping[int, tuple[str, ...]] = {
    1: ("jan", "jan.", "january"),
    2: ("feb", "feb.", "february"),
    3: ("mar", "mar.", "march"),
    4: ("apr", "apr.", "april"),
    5: ("may",),
    6: ("jun", "jun.", "june"),
    7: ("jul", "jul.", "july"),
    8: ("aug", "aug.", "august"),
    9: ("sep", "sep.", "sept", "sept.", "september"),
    10: ("oct", "oct.", "october"),
    11: ("nov", "nov.", "november"),
    12: ("dec", "dec.", "december"),
}

_MONTH_ALIASES: dict[str, int] = {
    alias: month
    for month, aliases in _MONTH_VARIANTS.items()
    for alias in aliases
}

_MONTH_PATTERN = "|".join(
    sorted((re.escape(alias) for alias in _MONTH_ALIASES), key=len, reverse=True)
)
_MONTH_FIRST_PATTERN = re.compile(
    rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{2,4}}))?",
    re.IGNORECASE,
)
_DAY_FIRST_PATTERN = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_PATTERN})(?:,?\s*(\d{{2,4}}))?",
    re.IGNORECASE,
)
_ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_EURO_DATE_PATTERN = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")

_TIME_24H_PATTERN = re.compile(r"\b(2[0-3]|[01]?\d):([0-5]\d)(?::([0-5]\d))?\b")
_TIME_12H_PATTERN = re.compile(
    r"\b(1[0-2]|0?[1-9])(?:[:.]([0-5]\d))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_DURATION_SEGMENT_PATTERN = re.compile(r"Duration:.*", re.IGNORECASE)
_DURATION_DAY_PATTERN = re.compile(r"(\d+)\s*(?:day|days)\b", re.IGNORECASE)
_DURATION_HOUR_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hour|hours)\b", re.IGNORECASE)
_DURATION_MINUTE_PATTERN = re.compile(r"(\d+)\s*(?:minute|minutes|min|mins)\b", re.IGNORECASE)
_DURATION_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")

_TIME_CACHE: dict[int, tuple[int | None, int | None, int | None]] = {}


def load_raw_events(json_source: Union[str, Path], encoding: str = "utf-8") -> list[JSONMapping]:
    """
    Load raw event payloads from a JSON file inside ``data/raw`` (or any other
    directory) and normalise the return value to a list of dictionaries.

    Parameters
    ----------
    json_source:
        Path to the JSON file.  Both absolute and repository-relative paths are
        accepted so callers can keep the function reusable across crawlers.
    encoding:
        Optional text encoding used when reading the file.  UTF-8 is the safe
        default because the raw dumps we store use it consistently.

    Returns
    -------
    list[Mapping[str, Any]]
        A list with the raw records from the file.  In case the JSON file only
        contains a single dictionary, the function wraps it in a list so the
        downstream pipeline can process items uniformly.
    """

    path = Path(json_source)
    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}")

    with path.open("r", encoding=encoding) as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]

    if isinstance(payload, Mapping):
        for candidate in ("events", "_items", "items", "data"):
            nested = payload.get(candidate)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, Mapping)]
        return [payload]

    raise ValueError(f"Unsupported JSON structure in {path}: {type(payload)}")


def filter_events_for_refreshments(
    records: Sequence[JSONMapping],
    keyword_rules: Mapping[str, Mapping[str, Any]] | None = None,
    text_fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Filter raw event dictionaries for those that mention refreshments.

    The function inspects all string fields (or a caller-specified subset) and
    searches for the refreshment keywords defined in :data:`REFRESHMENT_RULES`.
    When matches are found, the function returns the unmodified record together
    with a serialisable ``refreshment_details`` structure that mirrors the
    format produced by :func:`backend.amiv_api.infer_refreshments`.

    Parameters
    ----------
    records:
        Sequence of JSON-like dictionaries representing raw events.
    keyword_rules:
        Custom keyword configuration.  By default the module-level
        :data:`REFRESHMENT_RULES` is reused to keep the heuristics aligned.
    text_fields:
        Optional list of dotted paths (e.g. ``"metadata.description"``) that
        should be inspected.  When omitted, the function walks the entire
        structure and uses every textual fragment it can find.

    Returns
    -------
    list[dict]
        Each element contains the original ``record`` and the computed
        ``refreshment_details``.  Records without matches are omitted.
    """

    rules = keyword_rules or REFRESHMENT_RULES
    filtered: list[dict[str, Any]] = []

    for record in records:
        # Prepare everything for the regex search
        fragments = _extract_text_fragments(record, text_fields)
        corpus = _build_search_corpus(fragments)
        if not corpus:
            continue
        
        # Do the regex search to find refreshment keywords
        details = _match_refreshment_keywords(corpus, rules)
        if details["categories"]:
            filtered.append({"record": record, "refreshment_details": details})

    return filtered





def write_filtered_events(
    filtered_events: Sequence[Mapping[str, Any]],
    destination: Union[str, Path],
    field_mapping: Mapping[str, Union[str, Sequence[str], Callable[[JSONMapping], Any]]] | None = None,
    *,
    seen_titles: set,
    ensure_ascii: bool = False,
    indent: int = 2,
    encoding: str = "utf-8",
) -> list[dict[str, Any]]:
    """
    Serialise filtered events into the structure used by ``apero_results_example.json``.

    Parameters
    ----------
    filtered_events:
        Output from :func:`filter_events_for_refreshments`.  Each item must
        expose ``record`` and ``refreshment_details`` keys.
    destination:
        File path for the generated JSON export.  Parent directories are created
        automatically so the function can be used from scripts.
    field_mapping:
        Mapping that defines how to extract ``url``, ``title`` and related
        fields from the raw records.  Values can either be dotted keys (as
        strings), ordered sequences of fallback keys, or callables that receive
        the raw record.  When omitted, :data:`DEFAULT_FIELD_MAPPING` is used.
    ensure_ascii:
        Forwarded to :func:`json.dump`; keeping this ``False`` preserves any
        non-ASCII refreshments that appear in the source material.
    indent:
        Indentation level for the JSON output.  The reference file uses ``2`` so
        that remains the default.
    encoding:
        Text encoding used for writing the export file.

    Returns
    -------
    
    list[dict]
        The serialised list that was written to ``destination``.  Returning it
        makes unit testing straightforward because no file system access is
        required.
    """

    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    mapping_config = field_mapping or DEFAULT_FIELD_MAPPING
    serialised: list[dict[str, Any]] = []

    for item in filtered_events:
        record = item.get("record", {})
        details = item.get("refreshment_details", {})

        event_payload: MutableMapping[str, Any] = {}
        for field, extractor in mapping_config.items():
            event_payload[field] = _resolve_field(record, extractor)

        title = event_payload.get("title")
        if not is_title_present(title, seen_titles):
            seen_titles.add(title)
            # Ensure canonical date and time representations in the output.
            event_payload["date"] = _normalise_date_value(event_payload.get("date"))
            event_payload["start_time"] = _render_time_field(event_payload.get("start_time"))
            event_payload["end_time"] = _render_time_field(event_payload.get("end_time"))

            summary = details.get("summary")
            event_payload["refreshments"] = summary
            event_payload["refreshment_details"] = details
            serialised.append(dict(event_payload))

    with destination_path.open("w", encoding=encoding) as handle:
        json.dump(serialised, handle, ensure_ascii=ensure_ascii, indent=indent)

    return serialised


def _extract_text_fragments(record: JSONMapping, text_fields: Sequence[str] | None) -> list[str]:
    """Return textual fragments from ``record`` honouring the optional selector list."""

    if text_fields:
        fragments: list[str] = []
        for path in text_fields:
            value = _lookup_path(record, path)
            fragments.extend(_coerce_to_strings(value))
        return fragments

    return _coerce_to_strings(record)


def _coerce_to_strings(value: JSONValue) -> list[str]:
    """Collect human readable fragments from a nested JSON value."""

    if value is None:
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, Mapping):
        fragments: list[str] = []
        for nested in value.values():
            fragments.extend(_coerce_to_strings(nested))
        return fragments

    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        fragments: list[str] = []
        for item in value:
            fragments.extend(_coerce_to_strings(item))
        return fragments

    # Numbers and other scalar values are coerced to strings because they might
    # encode start times or similar metadata that contain keywords.
    return [str(value)]


def _build_search_corpus(fragments: Iterable[str]) -> str:
    """Construct a normalised, whitespace-collapsed search corpus."""

    cleaned = [
        normalize_text(fragment.lower()).strip()
        for fragment in fragments
        if fragment
    ]
    if not cleaned:
        return ""

    return re.sub(r"\s+", " ", " ".join(cleaned))


def extract_date_from_text(text: str) -> str | None:
    """
    Attempt to extract a ``YYYY-MM-DD`` date from the provided text fragment.

    The parser recognises a range of common formats, including ISO timestamps,
    European numeric notations (e.g. ``31.10.2025``) and month names with both
    short and long variants such as ``Oct.`` or ``October``.
    """

    if not text:
        return None

    match = _ISO_DATE_PATTERN.search(text)
    if match:
        year, month, day = map(int, match.groups())
        return _build_iso_date(year, month, day)

    for match in _MONTH_FIRST_PATTERN.finditer(text):
        month_token, day_token, year_token = match.groups()
        month = _parse_month_token(month_token)
        day = _parse_day_token(day_token)
        year = _coerce_year(year_token)
        if month and day and year:
            iso_date = _build_iso_date(year, month, day)
            if iso_date:
                return iso_date

    for match in _DAY_FIRST_PATTERN.finditer(text):
        day_token, month_token, year_token = match.groups()
        month = _parse_month_token(month_token)
        day = _parse_day_token(day_token)
        year = _coerce_year(year_token)
        if month and day and year:
            iso_date = _build_iso_date(year, month, day)
            if iso_date:
                return iso_date

    for match in _EURO_DATE_PATTERN.finditer(text):
        day_str, month_str, year_str = match.groups()
        try:
            day = int(day_str)
            month = int(month_str)
        except ValueError:
            continue
        year = _coerce_year(year_str)
        if year:
            iso_date = _build_iso_date(year, month, day)
            if iso_date:
                return iso_date

    return None


def _parse_month_token(token: str | None) -> int | None:
    """Convert a month token such as ``Oct.`` into its numeric representation."""

    if not token:
        return None
    normalised = token.strip().lower().rstrip(".")
    return _MONTH_ALIASES.get(normalised)


def _parse_day_token(token: str | None) -> int | None:
    """Convert day strings (including ordinals like ``31st``) into integers."""

    if not token:
        return None
    cleaned = re.sub(r"(st|nd|rd|th)$", "", token, flags=re.IGNORECASE)
    try:
        day = int(cleaned)
    except ValueError:
        return None
    return day if 1 <= day <= 31 else None


def _coerce_year(token: str | None) -> int | None:
    """Normalise year tokens, supporting both two and four digit representations."""

    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    try:
        year = int(token)
    except ValueError:
        return None

    if year < 100:
        # Treat 0-49 as 2000-2049 and 50-99 as 1950-1999.
        return year + 2000 if year <= 49 else year + 1900
    return year


def _build_iso_date(year: int, month: int, day: int) -> str | None:
    """Return a canonical ISO date string if the components constitute a valid date."""

    try:
        parsed = datetime(year, month, day)
    except ValueError:
        return None
    return parsed.strftime("%Y-%m-%d")


def _strip_duration_segments(text: str) -> str:
    """Remove trailing ``Duration: ...`` sections to avoid false-positive time matches."""

    if not text:
        return text
    return _DURATION_SEGMENT_PATTERN.sub("", text)


def _prepare_time_text(text: str) -> str:
    """Normalise meridian markers (am/pm) so they are easier to parse."""

    if not text:
        return ""

    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1).lower()}m"

    return re.sub(r"(?i)\b([ap])\.?\s*m\.?\b\.?", repl, text)


def _find_time_matches(text: str) -> list[tuple[int, tuple[int, int]]]:
    """Return minute offsets and string spans detected inside ``text``."""

    if not text:
        return []

    prepared = _prepare_time_text(text)
    matches: list[tuple[int, tuple[int, int]]] = []

    for match in _TIME_12H_PATTERN.finditer(prepared):
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        meridian = match.group(3).lower()
        if meridian == "pm" and hour != 12:
            hour += 12
        if meridian == "am" and hour == 12:
            hour = 0
        matches.append((hour * 60 + minute, match.span()))

    for match in _TIME_24H_PATTERN.finditer(prepared):
        hour = int(match.group(1))
        minute = int(match.group(2))
        matches.append((hour * 60 + minute, match.span()))

    seen: set[int] = set()
    unique: list[tuple[int, tuple[int, int]]] = []
    for minutes, span in matches:
        if minutes not in seen:
            seen.add(minutes)
            unique.append((minutes, span))
    return unique


def _search_times_in_text(text: str) -> list[int]:
    """Return ordered unique minute-offsets extracted from ``text``."""

    return [minutes for minutes, _ in _find_time_matches(text)]


def _has_time_range_indicator(text: str) -> bool:
    """Heuristic to determine whether ``text`` expresses a time range."""

    lower = text.lower()
    for token in (" - ", " – ", " — ", " to ", " until ", " bis "):
        if token in lower:
            return True
    return False


def _normalise_time_value(value: Any) -> int | None:
    """Extract the first time-of-day (minutes after midnight) from ``value``."""

    if value is None:
        return None

    if isinstance(value, str):
        cleaned = _strip_duration_segments(value)
        times = _search_times_in_text(cleaned)
        return times[0] if times else None

    if isinstance(value, (int, float)):
        # Plain numbers are ambiguous (could be durations or IDs), so skip them.
        return None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            minutes = _normalise_time_value(item)
            if minutes is not None:
                return minutes
        return None

    if isinstance(value, Mapping):
        for item in value.values():
            minutes = _normalise_time_value(item)
            if minutes is not None:
                return minutes
        return None

    return None


def _parse_duration_value(value: Any) -> int | None:
    """Extract duration in minutes from heterogenous ``value`` representations."""

    if value is None:
        return None

    if isinstance(value, str):
        return _parse_duration_string(value)

    if isinstance(value, (int, float)):
        # Interpret integers as minutes only if they are small (heuristic).
        return int(value) if value and value < 24 * 60 * 10 else None

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            minutes = _parse_duration_value(item)
            if minutes is not None:
                return minutes
        return None

    if isinstance(value, Mapping):
        for item in value.values():
            minutes = _parse_duration_value(item)
            if minutes is not None:
                return minutes
        return None

    return None


def _parse_duration_string(text: str) -> int | None:
    """Parse human readable duration descriptions into minute offsets."""

    if not text:
        return None

    lower = text.lower()
    relevant = lower
    marker_index = lower.find("duration")
    if marker_index != -1:
        relevant = lower[marker_index:]

    total_minutes = 0

    for match in _DURATION_DAY_PATTERN.finditer(relevant):
        total_minutes += int(match.group(1)) * 24 * 60

    clock_match = _DURATION_TIME_PATTERN.search(relevant)
    if clock_match:
        hours = int(clock_match.group(1))
        minutes = int(clock_match.group(2))
        seconds = int(clock_match.group(3)) if clock_match.group(3) else 0
        total_minutes += hours * 60 + minutes + seconds // 60

    for match in _DURATION_HOUR_PATTERN.finditer(relevant):
        hours = float(match.group(1))
        total_minutes += int(hours * 60)

    for match in _DURATION_MINUTE_PATTERN.finditer(relevant):
        total_minutes += int(match.group(1))

    return total_minutes or None


def _wrap_minutes(value: int | None) -> int | None:
    """Normalise ``value`` to the ``0..1439`` range."""

    if value is None:
        return None
    return value % (24 * 60)


def _format_minutes(value: int | None) -> str | None:
    """Render minute offsets as ``HH:MM`` 24-hour strings."""

    if value is None:
        return None
    minutes = _wrap_minutes(value)
    if minutes is None:
        return None
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}"


def _render_time_field(value: Any) -> str | None:
    """Ensure consistent string formatting for exported time-of-day fields."""

    minutes = _normalise_time_value(value)
    return _format_minutes(minutes)


def _match_refreshment_keywords(
    corpus: str,
    rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Compare ``corpus`` against ``rules`` and return structured refreshment data.
    """

    matches: dict[str, list[str]] = {}

    for category, configuration in rules.items():
        keywords = configuration.get("keywords", set()) or set()
        hits = sorted(
            keyword
            for keyword in keywords
            if keyword and _keyword_in_corpus(keyword, corpus)
        )
        if hits:
            matches[category] = hits

    if not matches:
        return {"categories": [], "matches": {}, "summary": None}

    ordered_categories = [
        category for category in REFRESHMENT_DISPLAY_PRIORITY if category in matches
    ] + [category for category in matches if category not in REFRESHMENT_DISPLAY_PRIORITY]

    summary = _format_refreshment_summary(ordered_categories, matches, rules)

    return {
        "categories": ordered_categories,
        "matches": matches,
        "summary": summary,
    }


def _keyword_in_corpus(keyword: str, corpus: str) -> bool:
    """Return ``True`` when ``keyword`` appears in the prepared ``corpus``."""

    normalised_keyword = normalize_text(keyword.lower())
    normalised_keyword = re.sub(r"\s+", " ", normalised_keyword).strip()
    return bool(normalised_keyword) and normalised_keyword in corpus


def _format_refreshment_summary(
    categories: Sequence[str],
    matches: Mapping[str, Sequence[str]],
    rules: Mapping[str, Mapping[str, Any]],
) -> str:
    """Create the human readable ``refreshments`` string shown in the UI."""

    summaries: list[str] = []
    for category in categories:
        label = rules.get(category, {}).get("label", category.title())
        keywords = list(matches.get(category, []))
        if not keywords:
            summaries.append(label)
            continue
        snippets = ", ".join(keywords[:3])
        summaries.append(f"{label} ({snippets})")
    return " · ".join(summaries)


def _extract_start_time_from_record(record: JSONMapping) -> str | None:
    """Return the inferred start time from ``record``."""

    start, _ = _extract_times_from_record(record)
    return _format_minutes(start)


def _extract_end_time_from_record(record: JSONMapping) -> str | None:
    """Return the inferred end time from ``record``."""

    _, end = _extract_times_from_record(record)
    return _format_minutes(end)


def _extract_times_from_record(record: JSONMapping) -> tuple[int | None, int | None]:
    """Infer start and end times (in minutes) from structured and free-text inputs."""

    cache_key = id(record)
    cached = _TIME_CACHE.get(cache_key)
    if cached:
        return cached[0], cached[1]

    start_minutes: int | None = None
    end_minutes: int | None = None
    duration_minutes: int | None = None

    metadata = record.get("metadata") if isinstance(record, Mapping) else None

    start_candidates = [
        record.get("start_time") if isinstance(record, Mapping) else None,
        record.get("time_start") if isinstance(record, Mapping) else None,
        metadata.get("start_time") if isinstance(metadata, Mapping) else None,
        metadata.get("time_start") if isinstance(metadata, Mapping) else None,
    ]
    for candidate in start_candidates:
        start_minutes = _normalise_time_value(candidate)
        if start_minutes is not None:
            break

    end_candidates = [
        record.get("end_time") if isinstance(record, Mapping) else None,
        record.get("time_end") if isinstance(record, Mapping) else None,
        metadata.get("end_time") if isinstance(metadata, Mapping) else None,
        metadata.get("time_end") if isinstance(metadata, Mapping) else None,
    ]
    for candidate in end_candidates:
        end_minutes = _normalise_time_value(candidate)
        if end_minutes is not None:
            break

    duration_candidates = [
        record.get("duration") if isinstance(record, Mapping) else None,
        metadata.get("duration") if isinstance(metadata, Mapping) else None,
    ]
    for candidate in duration_candidates:
        duration_minutes = _parse_duration_value(candidate)
        if duration_minutes is not None:
            break

    text_fields = (
        "metadata.title",
        "metadata.description",
        "markdown",
        "extracted_content",
        "html",
    )

    if start_minutes is None or end_minutes is None or duration_minutes is None:
        for fragment in _extract_text_fragments(record, text_fields):
            if not fragment:
                continue

            if duration_minutes is None and "duration" in fragment.lower():
                duration_minutes = _parse_duration_string(fragment)

            cleaned_fragment = _strip_duration_segments(fragment)
            matches = _find_time_matches(cleaned_fragment)
            times = [value for value, _ in matches]

            if start_minutes is None and times:
                start_minutes = times[0]

            if end_minutes is None and len(matches) >= 2:
                start_span = matches[0][1]
                end_span = matches[1][1]
                between = cleaned_fragment[start_span[1]:end_span[0]]
                if _has_time_range_indicator(between):
                    candidate = times[1]
                    if start_minutes is None:
                        start_minutes = times[0]
                    if candidate != start_minutes:
                        end_minutes = candidate

            if start_minutes is not None and end_minutes is not None and duration_minutes is not None:
                break

    if start_minutes is not None and end_minutes is None and duration_minutes is not None:
        end_minutes = start_minutes + duration_minutes
    if end_minutes is not None and start_minutes is None and duration_minutes is not None:
        start_minutes = end_minutes - duration_minutes

    start_minutes = _wrap_minutes(start_minutes)
    end_minutes = _wrap_minutes(end_minutes)

    _TIME_CACHE[cache_key] = (start_minutes, end_minutes, duration_minutes)
    return start_minutes, end_minutes


def _extract_date_from_record(record: JSONMapping) -> str | None:
    """
    Derive a calendar date from the raw record using metadata and textual hints.
    """

    metadata = record.get("metadata") if isinstance(record, Mapping) else None
    candidate_values: list[Any] = []
    if isinstance(metadata, Mapping):
        candidate_values.append(metadata.get("date"))

    candidate_values.extend(
        [
            record.get("date"),
            record.get("time_start"),
            record.get("start_date"),
        ]
    )

    for value in candidate_values:
        normalised = _normalise_date_value(value)
        if normalised:
            return normalised

    text_fields = (
        "metadata.date",
        "metadata.title",
        "metadata.description",
        "markdown",
        "extracted_content",
        "html",
    )
    for fragment in _extract_text_fragments(record, text_fields):
        normalised = extract_date_from_text(fragment)
        if normalised:
            return normalised

    return None


def _normalise_date_value(value: Any) -> str | None:
    """Convert date-like values into ISO strings where possible."""

    if value is None:
        return None

    if isinstance(value, str):
        return extract_date_from_text(value)

    if isinstance(value, (int, float)):
        return extract_date_from_text(str(int(value)))

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for entry in value:
            normalised = _normalise_date_value(entry)
            if normalised:
                return normalised
        return None

    if isinstance(value, Mapping):
        for entry in value.values():
            normalised = _normalise_date_value(entry)
            if normalised:
                return normalised
        return None

    return None


def _resolve_field(
    record: JSONMapping,
    extractor: Union[str, Sequence[str], Callable[[JSONMapping], Any]],
) -> Any:
    """Resolve a single export field using either dotted keys or callables."""

    if callable(extractor):
        return extractor(record)

    if isinstance(extractor, str):
        if extractor == "_extracted_date":
            return _extract_date_from_record(record)
        if extractor == "_extracted_start_time":
            return _extract_start_time_from_record(record)
        if extractor == "_extracted_end_time":
            return _extract_end_time_from_record(record)
        return _lookup_path(record, extractor)

    if isinstance(extractor, Sequence):
        for candidate in extractor:
            value = _resolve_field(record, candidate)  # type: ignore[arg-type]
            if value is not None:
                return value
        return None

    return None


def _lookup_path(record: JSONMapping, path: str) -> Any:
    """Resolve dotted ``path`` expressions against ``record``."""

    if not path:
        return None

    # Special handling for simple slicing hints (e.g. ``time_start[:10]``) so we
    # can derive date strings from ISO timestamps when needed.
    slice_hint = None
    if "[" in path and path.endswith("]"):
        base, _, tail = path.partition("[")
        slice_hint = tail.strip("[]")
        path = base
    current: Any = record
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, Sequence) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError:
                return None
        else:
            return None

    if slice_hint and isinstance(current, str):
        slice_match = re.fullmatch(r":?(\d+)?", slice_hint)
        if slice_match:
            end = slice_match.group(1)
            return current[: int(end)] if end else current

    return current
################################################-test


def is_title_present(title: str, seen_titles: set, score_threshold: int = 80) -> bool:
    """
    Check if a similar title is already in the set of seen titles.
    """
    if not title:
        return False
    for seen_title in seen_titles:
        if fuzz.partial_ratio(title, seen_title) >= score_threshold:
            return True
    return False


def main() -> None:
    """
    Convenience entry point that filters the VMP crawl dump and writes the result.

    This mirrors the pattern used by :mod:`backend.crawler`: the function uses the data/raw/VMP_data.json file as
    a default input and later overri
    on the raw data captured in ``data/raw/VMP_data.json`` and produces a
    calendar-compatible JSON file that only contains events mentioning food,
    drinks or snacks.  Paths can be overridden when the function is invoked from
    scripts or tests.
    """
    seen_titles = set()

    # Minimal batch processing similar to backend.crawler::main
    configs = [
        {"source": Path("data/raw/VMP_data.json"), "destination": Path("data/apero_results_vmp.json")},
        {"source": Path("data/raw/VIS_data.json"), "destination": Path("data/apero_results_vis.json")},
        # Add more mappings here if needed
    ]

    for cfg in configs:
        src = cfg["source"]
        dst = cfg["destination"]

        try:
            records = load_raw_events(src)
        except FileNotFoundError:
            print(f"Source file not found: {src}. Skipping.")
            continue
    # The crawler stores fairly verbose HTML and Markdown snippets; prioritise
    # those fields to keep the keyword search focused.


        filtered = filter_events_for_refreshments(
            records,
            text_fields=("markdown", "extracted_content", "html", "metadata.title"),
        )
        write_filtered_events(filtered, dst, seen_titles=seen_titles)

        print(
            f"Processed {len(records)} records for {src}, "
            f"found {len(filtered)} refreshment events. "
            f"Output written to {dst}."
        ) 


if __name__ == "__main__":
    main()
