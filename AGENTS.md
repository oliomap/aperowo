# Org Learnings
<!-- Patterns and insights discovered by the autonomous org -->

## Source Patterns

## Code Patterns
- **Greedy regex day matching**: In date-parsing regexes, `(\d+)` for a day group can greedily consume the first digits of a four-digit year (e.g., `20` from `2026`). Always use `(\d{1,2})` for day/month capture groups to prevent this. Discovered in `_MONTH_FIRST_RE` (Sprint 20260322-0851).

## Anti-patterns
- Don't modify `data/events.json` directly — let the pipeline handle it
- Don't modify `.env` or secrets from agent code
