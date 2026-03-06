# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Apero wo?** is a tool for the ETH Zurich community to discover aperos and free food events on campus. It has a Python backend that crawls event sources and a Node.js/Express frontend that displays results in a calendar UI.

## Architecture

The project has three layers that form a pipeline:

1. **Crawling** (`backend/crawler.py`) — Uses `crawl4ai` (async BFS deep crawl) to scrape event pages from ETH student organizations (VIS, VMP, ARCH). Crawl targets are configured in `backend/urls_to_crawl.json`. Raw HTML/markdown results are saved to `data/raw/`.

2. **Filtering & enrichment** (`backend/filter.py`) — Loads raw crawl dumps from `data/raw/`, applies keyword-based refreshment detection (reusing rules from `amiv_api.py`), extracts dates/times from free text, computes an "ease of entry" score, deduplicates by fuzzy title matching, and writes structured JSON to `data/apero_results_*.json`.

3. **AMIV API** (`backend/amiv_api.py`) — Separate path for AMIV events fetched via their REST API (paginated, `_items` key). Applies the same refreshment keyword rules (`REFRESHMENT_RULES`) and outputs the same event schema.

4. **Frontend** (`frontend/`) — Express server serving static files from `frontend/public/` and JSON data from `data/` via a `/data/*` route. The calendar UI (`public/app.js`) fetches `apero_results_*.json` files, normalizes entries, and renders a month/week calendar with event cards.

### Key data flow

```
ETH event sites  -->  crawler.py (crawl4ai)  -->  data/raw/*.json
AMIV API         -->  amiv_api.py            -->  (in-memory)
                      filter.py              -->  data/apero_results_*.json
                      frontend/server.js     -->  browser calendar UI
```

### Shared concepts

- **Refreshment rules** (`REFRESHMENT_RULES` in `amiv_api.py`) define keyword sets for drinks, food, snacks, and desserts. Both `amiv_api.py` and `filter.py` use these for consistent detection.
- **Ease of entry** scoring in `filter.py` uses weighted keyword rules to estimate event accessibility (0–1 scale).
- Event JSON schema used by the frontend: `{ url, title, date, start_time, end_time, location, refreshments, refreshment_details, easeOfEntry }`.

## Commands

### Backend (Python)

```bash
# Set up virtual environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the async crawler (writes to data/raw/)
python -m backend.crawler

# Run the AMIV API fetcher
python -m backend.amiv_api

# Run the filter pipeline (reads data/raw/, writes data/apero_results_*.json)
python -m backend.filter
```

### Frontend (Node.js)

```bash
cd frontend
npm install

# Development with hot reload
npm run dev

# Production
npm start
```

The frontend runs on port 3000 by default (configurable via `PORT` env var).

## Data Directory

- `data/raw/` — Raw crawl output (VMP_data.json, VIS_data.json, AMIV_data.json, ARCH_data.json)
- `data/apero_results_*.json` — Filtered/enriched event data consumed by the frontend
- These JSON files are intentionally tracked in git (needed for GitHub Pages static hosting)

## Notes

- The frontend is vanilla JS with no build step or framework — just `public/index.html`, `public/styles.css`, and `public/app.js`.
- `backend/webscraper.py` is an older standalone scraper (uses `requests` + `BeautifulSoup`) that predates the `crawl4ai`-based crawler. The active pipeline uses `crawler.py` + `filter.py`.
- Text normalization strips diacritical marks for keyword matching (important for German text like "Glühwein").
- The frontend `/data/*` route includes path traversal protection via `resolveDataPath`.
