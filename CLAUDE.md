# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Apero wo?** is a tool for the ETH Zurich community to discover aperos and free food events on campus. It has a Python backend that crawls ~35 event sources and a Node.js/Express frontend that displays results in a calendar UI.

## Architecture

The backend is a pipeline that crawls, extracts, filters, scores, and deduplicates events into a single `data/events.json`.

```
Sources (crawl4ai / API / Eventbrite)
  → Extraction (Gemini AI or regex fallback)
  → Food detection (keyword matching via REFRESHMENT_RULES)
  → Ease-of-entry scoring (Gemini AI or keyword fallback)
  → Dedup (fuzzy title matching)
  → data/events.json
  → Frontend calendar UI
```

### Backend structure (`backend/`)

- `pipeline.py` — Main orchestrator: `async run()` processes all sources end-to-end
- `config.py` — Loads `sources.json`, instantiates source adapters
- `normalize.py` — Slugify, event ID generation, fuzzy dedup
- `sources/` — Source adapters (BaseSource ABC)
  - `crawl4ai_source.py` — Generic web crawler using crawl4ai + Playwright
  - `amiv_api_source.py` — AMIV REST API with pagination
  - `eventbrite_source.py` — Eventbrite organizer page scraper
- `extraction/` — Structured event extraction from raw content
  - `gemini_extractor.py` — Gemini-powered extraction (when API key set)
  - `regex_extractor.py` — Fallback: date/time/location via regex
  - `extractor.py` — Dispatcher: tries Gemini, falls back to regex
- `filtering/` — Food/drink detection
  - `refreshments.py` — REFRESHMENT_RULES keyword matching (single source of truth)
  - `food_detector.py` — Determines if event has free food, builds food_type string
- `scoring/` — Ease-of-entry scoring
  - `gemini_scorer.py` — Gemini-based scoring with rubric
  - `ease_of_entry.py` — Keyword-based weighted scoring fallback
- `sources.json` — Declarative registry of all ~35 ETH event sources

### Frontend (`frontend/`)

- Express server serving static files + `/data/*` route for JSON
- Vanilla JS calendar UI (no build step, no framework)
- `public/app.js` fetches single `data/events.json`, renders month/week calendar with event cards
- Event cards show: source badge, food type badge, time/location, refreshment details, ease-of-entry meter, event link

### Gemini AI integration

Two uses: structured extraction and ease-of-entry scoring. Both are optional — the system works fully without an API key via regex/keyword fallbacks. Enable by setting `GEMINI_API_KEY` in `.env` (see `.env.example`).

## Commands

### Backend (Python)

```bash
# Set up virtual environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the full pipeline (writes data/events.json)
python main.py
```

### Frontend (Node.js)

```bash
cd frontend
npm install
npm run dev    # Development with hot reload
npm start      # Production
```

The frontend runs on port 3000 by default (configurable via `PORT` env var).

## Data

- `data/events.json` — Single merged output consumed by the frontend (tracked in git for GitHub Pages)
- Event schema: `{ id, source, title, date, start_time, end_time, location, url, food_type, refreshments, refreshment_details, easeOfEntry, easeOfEntry_method, scraped_at }`

## Notes

- Text normalization strips diacritics for keyword matching (important for German text like "Glühwein")
- The frontend `/data/*` route includes path traversal protection via `resolveDataPath`
- Rate limiting: 4s delay between Gemini API calls to stay within free tier (15 RPM)
