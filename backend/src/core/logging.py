"""Centralised logging configuration.

A single :func:`configure_logging` call wires up structured, level-aware logging
for the API process and Celery workers alike, keeping formatting identical
across every runtime.
"""

from __future__ import annotations

import logging
import sys
from logging.config import dictConfig

from src.core.config import settings

_CONFIGURED: bool = False


def configure_logging() -> None:
    """Configure the root logger idempotently.

    Safe to call multiple times (e.g. once per worker fork); the guard flag
    prevents duplicate handler registration that would otherwise double every
    log line.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": ("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"),
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": sys.stdout,
                },
            },
            "root": {
                "level": settings.log_level.upper(),
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn.access": {"level": "WARNING", "propagate": True},
                "sqlalchemy.engine": {
                    "level": "WARNING" if not settings.debug else "INFO",
                    "propagate": True,
                },
            },
        }
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, configuring logging on first use."""
    configure_logging()
    return logging.getLogger(name)
