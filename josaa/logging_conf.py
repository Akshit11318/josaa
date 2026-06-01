"""Central logging setup. Pretty colored console (Rich) + a rolling file log.

Call `setup_logging()` once at process start (CLI / web). Modules just do
`from .logging_conf import get_logger; log = get_logger(__name__)`.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

_CONFIGURED = False
LOG_DIR = Path("logs")


def setup_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console: colored, human-friendly.
    console = RichHandler(rich_tracebacks=True, show_path=False, markup=True,
                          omit_repeated_times=False)
    console.setFormatter(logging.Formatter("%(message)s", datefmt="%H:%M:%S"))
    root.addHandler(console)

    # File: full detail for later inspection.
    try:
        LOG_DIR.mkdir(exist_ok=True)
        fileh = RotatingFileHandler(LOG_DIR / "josaa.log", maxBytes=5_000_000, backupCount=3)
        fileh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(fileh)
    except OSError:
        pass  # read-only fs — console logging still works

    # Quiet noisy third parties.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str = "josaa") -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
