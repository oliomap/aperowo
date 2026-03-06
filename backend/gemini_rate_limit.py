"""Shared Gemini API rate limiter for concurrent pipeline execution."""

import asyncio

# Single lock ensuring only one Gemini API call runs at a time.
gemini_lock = asyncio.Lock()

# Delay between API calls: Gemini free tier = 15 RPM → 4s minimum.
RATE_LIMIT_DELAY = 4.0
