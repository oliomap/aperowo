"""Logging configuration for the pipeline.

Sets up a logger that writes to both console (INFO, colored) and a rotating
file in logs/ (DEBUG) with timestamps and source context.
"""

from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

_configured = False

# ANSI color codes
_RESET = "\033[0m"
_COLORS = {
    logging.DEBUG: "\033[36m",      # cyan
    logging.INFO: "\033[32m",       # green
    logging.WARNING: "\033[33m",    # yellow
    logging.ERROR: "\033[31m",      # red
    logging.CRITICAL: "\033[1;31m", # bold red
}
_DIM = "\033[2m"
_BOLD = "\033[1m"


class ColorFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes to console output."""

    def format(self, record: logging.LogRecord) -> str:
        color = _COLORS.get(record.levelno, "")
        level = f"{color}{record.levelname:<8}{_RESET}"
        name = f"{_DIM}{record.name.removeprefix('aperowo.')}{_RESET}"
        timestamp = f"{_DIM}{self.formatTime(record, self.datefmt)}{_RESET}"
        msg = record.getMessage()

        if record.levelno >= logging.WARNING:
            msg = f"{color}{msg}{_RESET}"

        formatted = f"{timestamp}  {level}  [{name}]  {msg}"

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            formatted += f"\n{_COLORS[logging.ERROR]}{record.exc_text}{_RESET}"

        return formatted


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring root handlers on first call."""
    global _configured
    if not _configured:
        _configure()
        _configured = True
    return logging.getLogger(name)


def _configure() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("aperowo")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    # Clear any handlers that may have been added by third-party libraries
    root.handlers.clear()

    plain_fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — INFO and above, colored
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(ColorFormatter(datefmt="%H:%M:%S"))

    # File handler — DEBUG and above, one file per run
    log_file = LOGS_DIR / f"pipeline_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(plain_fmt)

    root.addHandler(console)
    root.addHandler(file_handler)
