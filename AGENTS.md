# Org Learnings
<!-- Patterns and insights discovered by the autonomous org -->

## Environment & Tooling
- **Python Venv:** Always use the virtual environment at `.venv/`. Run tests and scripts using `.venv/bin/python` or `.venv/bin/pytest`.
- **Dependencies:** `crawl4ai` and others are installed in the `.venv`. Do not use the host's system python for this project.

## Source Patterns
- AMIV API changes pagination format ~quarterly. Check `next` field.

## Code Patterns
- Always use `normalize_text()` before keyword matching (German diacritics)

## Anti-patterns
- Don't modify `data/events.json` directly — let the pipeline handle it