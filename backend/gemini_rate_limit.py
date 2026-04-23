"""Shared Gemini API rate limiter and key rotation for concurrent pipeline execution."""

import asyncio
import os

from google.genai.errors import ClientError, ServerError

# Single lock ensuring only one Gemini API call runs at a time.
gemini_lock = asyncio.Lock()

# Delay between API calls: Gemini 3.1 Flash Lite free tier = 15 RPM → 4s minimum.
RATE_LIMIT_DELAY = 4.0

# Key rotation: try primary key first, fall back to secondary on 429.
_ENV_KEYS = ("GEMINI_API_KEY", "GEMINI_API_KEY_2")
_active_key_index = 0
_exhausted_keys: set[int] = set()


def get_api_key() -> str | None:
    """Return the currently active API key, or None if all are exhausted/unset."""
    if len(_exhausted_keys) >= len(_ENV_KEYS):
        return None
    for i in range(_active_key_index, _active_key_index + len(_ENV_KEYS)):
        idx = i % len(_ENV_KEYS)
        if idx in _exhausted_keys:
            continue
        key = os.environ.get(_ENV_KEYS[idx])
        if key:
            return key
    return None


def rotate_key() -> bool:
    """Mark the current key as exhausted and switch to the next one.

    Returns True if a fresh key is available, False if all keys are exhausted.
    """
    global _active_key_index
    _exhausted_keys.add(_active_key_index)
    for offset in range(1, len(_ENV_KEYS)):
        idx = (_active_key_index + offset) % len(_ENV_KEYS)
        if idx not in _exhausted_keys and os.environ.get(_ENV_KEYS[idx]):
            _active_key_index = idx
            return True
    return False


def is_quota_error(exc: Exception) -> bool:
    """Check if an exception is a Gemini 429 quota exhaustion error."""
    return isinstance(exc, ClientError) and exc.code == 429


def is_unavailable_error(exc: Exception) -> bool:
    """Check if an exception is a Gemini 503 UNAVAILABLE (overload) error."""
    if isinstance(exc, ServerError) and getattr(exc, "code", None) == 503:
        return True
    return "503" in str(exc) and "UNAVAILABLE" in str(exc)
