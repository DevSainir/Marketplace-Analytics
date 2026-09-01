"""Centralised logging configuration.

A single :func:`configure_logging` call wires up level-aware logging for the API
process and Celery workers alike, keeping formatting identical across every
runtime.

**Two formats, and the choice is not cosmetic** (register P2.2).

Locally, the human format: a person reading a terminal wants columns, not
braces. In production, JSON — one object per line, every value encoded.

JSON is what makes the output *safe*, not merely searchable. A log line is
assembled from strings the caller partly controls — a path, an email, a
workspace name, the text of an upstream error — and in a delimiter-separated
format those strings can pretend to be structure: a newline forges a whole line,
a `|` forges a field. Today full line-forging happens to be blocked for the one
value most exposed to it, because Python's URL parser strips newlines out of
`request.url.path` — which is a protection this codebase neither wrote nor can
rely on, and which does not extend to anything else that gets logged. Under a
JSON encoder the question stops being asked: a newline inside a value is
`\n` inside a quoted string, and there is no delimiter to spoof because
structure is carried by the encoding rather than by punctuation.

The request/actor/tenant fields come from :mod:`src.core.logcontext` and are
attached by the formatter, so no call site has to pass them.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from logging.config import dictConfig
from typing import Any

from src.core.config import settings
from src.core.logcontext import current_context

#: Attributes ``logging`` puts on every record. Anything else a caller passed
#: through ``extra=`` is ours and is worth emitting.
_STANDARD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with the request context folded in.

    Field order is deliberate: time, level and logger first, so a human tailing
    the raw stream can still read it left to right, and the message before the
    context so the eye finds the sentence before the metadata.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render a record as a single-line JSON object.

        Args:
            record: The log record.

        Returns:
            Compact JSON. ``ensure_ascii`` is left ON: the logs carry Russian
            text throughout, and an escaped payload survives every shipper,
            terminal and grep that a raw multi-byte one does not.
        """
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(current_context())
        # Anything a caller attached with `extra=`; this is how a structured
        # event carries its own fields instead of formatting them into prose.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # `default=str` so a UUID, a Decimal or a datetime in `extra` becomes a
        # string instead of crashing the log call. A logger that raises while
        # reporting a problem is the worst possible failure mode.
        return json.dumps(payload, default=str)


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
                "json": {"()": f"{__name__}.JsonFormatter"},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json" if settings.log_json else "standard",
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
