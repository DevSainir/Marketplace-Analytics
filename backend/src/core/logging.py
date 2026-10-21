"""Centralised logging configuration, built on structlog (register P2.2).

A single :func:`configure_logging` call wires up level-aware logging for the API
process and Celery workers alike, keeping formatting identical across every
runtime.

**Two formats, and the choice is not cosmetic.**

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
`\\n` inside a quoted string, and there is no delimiter to spoof because
structure is carried by the encoding rather than by punctuation.

structlog owns the pipeline; stdlib owns the transport
------------------------------------------------------
Every line in the process — ours, uvicorn's, Celery's, SQLAlchemy's — is
rendered by ONE structlog processor chain, reached through
:class:`structlog.stdlib.ProcessorFormatter` attached to the stdlib handler.
That arrangement is the point of using structlog here rather than a second
logging façade beside the first.

The reason is the redaction processor. A library writes lines about the same
request we do — an httpx warning carrying a proxy URL, a SQLAlchemy error
carrying a parameter, a Celery traceback carrying a task's arguments — and a
scrubber wired only into our own logger would be a control that covers the call
sites least likely to leak and misses the ones most likely to. There is one
chain, so there is one answer to "is this line scrubbed".

Two entry points, and which to use
----------------------------------
:func:`get_logger` returns a stdlib :class:`logging.Logger` and is what the
existing several-hundred call sites use: ``logger.info("served %s", path)``.
:func:`get_struct_logger` returns a structlog logger for new code that wants
key-value events — ``log.info("harvest finished", rows=1200, source="funnel")``
— which is the shape an alert binds to. Both land in the same chain; the
difference is only how comfortable the call site is to write.

The request/actor/tenant fields come from :mod:`src.core.logcontext` and are
attached by a processor, so no call site has to pass them.
"""

from __future__ import annotations

import logging
import sys
from logging.config import dictConfig
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, Processor, WrappedLogger

from src.core.config import settings
from src.core.logcontext import current_context
from src.core.observability.scrubbing import scrub_event

#: Field order in a rendered line. Time, level and logger first, so a human
#: tailing the raw stream can still read it left to right; the message before
#: the context so the eye finds the sentence before the metadata; the
#: correlation ids immediately after it, because they are what the next action
#: (a search) is built from.
_FIELD_ORDER: tuple[str, ...] = (
    "ts",
    "level",
    "logger",
    "message",
    "trace_id",
    "request_id",
    "task_id",
    "task_name",
    "method",
    "path",
    "status",
    "duration_ms",
    "client_ip",
    "user_id",
    "organization_id",
    "workspace_id",
)


def _merge_log_context(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Fold in whoever was asking, from :mod:`src.core.logcontext`.

    Bound fields win over the context only where a call site deliberately set
    the same key, which is why the context is applied *underneath* rather than
    over the top: a task that logs its own ``task_id`` for a child job should
    not have it silently replaced by the parent's.
    """
    context = current_context()
    for key, value in context.items():
        event_dict.setdefault(key, value)
    return event_dict


def _scrub(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Remove credentials from the event, whatever shape they arrived in.

    Placed after every processor that ADDS content (context, extras, the
    formatted exception) and before the renderer, so nothing can be introduced
    downstream of the only thing that redacts. Moving this earlier in the chain
    is the one edit here that silently weakens a control —
    ``tests/unit/core/test_log_redaction.py`` fails if the exception text stops
    being covered.
    """
    return scrub_event(dict(event_dict))


def _rename_event_to_message(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Call the sentence ``message``, which is what every shipper expects.

    structlog names it ``event``; Loki, Sentry and the JSON the previous
    formatter emitted all say ``message``. Renaming here rather than
    reconfiguring every call site keeps the wire format stable across this
    change — the lines already in production and the lines after it parse the
    same way.
    """
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict


def _uppercase_level(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Keep ``level`` spelled the way the deployed lines already spell it.

    structlog writes ``"info"``; the formatter this replaced wrote
    ``record.levelname``, i.e. ``"INFO"``. The difference is invisible to a
    human and load-bearing for everything else: a Loki query, a Grafana panel
    or an alert rule written against the lines already in production matches
    exactly one of the two spellings, and a rollout that silently changes it
    turns "no errors" into "no matches" — the two most dangerous readings to
    confuse.

    Backwards compatibility is the whole reason, so this is one of the few
    places in this package where the older convention wins over the library's.
    """
    level = event_dict.get("level")
    if isinstance(level, str):
        event_dict["level"] = level.upper()
    return event_dict


def _order_fields(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Reorder the event dict so a rendered line reads in a fixed order.

    Cosmetic for a parser, which sees an object; not cosmetic for the person
    reading `docker logs` during an incident, who is scanning columns.
    """
    ordered: EventDict = {key: event_dict[key] for key in _FIELD_ORDER if key in event_dict}
    ordered.update({key: value for key, value in event_dict.items() if key not in ordered})
    return ordered


def _shared_processors() -> list[Processor]:
    """The chain applied to every record, whichever logger produced it."""
    return [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]


def _tail_processors() -> list[Processor]:
    """The chain applied once, immediately before rendering.

    Order is load-bearing: context and exception text are added, *then*
    scrubbed, then renamed and ordered. See :func:`_scrub`.
    """
    return [
        _merge_log_context,
        structlog.processors.format_exc_info,
        _scrub,
        _rename_event_to_message,
        _uppercase_level,
        _order_fields,
    ]


class JsonFormatter(structlog.stdlib.ProcessorFormatter):
    """One JSON object per record, with the request context folded in.

    Kept as a named class rather than an inline configuration because it is the
    unit the logging contract is tested against
    (``tests/unit/core/test_structured_logging.py`` formats a record and parses
    the result). A test that goes through the same object production does is
    what makes "one parseable line, whatever a caller put in it" a property of
    the deployment rather than of the test's own setup.

    ``ensure_ascii`` is left ON: the logs carry Russian text throughout, and an
    escaped payload survives every shipper, terminal and grep that a raw
    multi-byte one does not. ``default=str`` so a UUID, a Decimal or a datetime
    in ``extra`` becomes a string instead of crashing the log call — a logger
    that raises while reporting a problem is the worst possible failure mode.
    """

    def __init__(self) -> None:
        """Build the formatter with this application's chain baked in."""
        super().__init__(
            processors=[
                *_tail_processors(),
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(default=str, ensure_ascii=True),
            ],
            foreign_pre_chain=[*_shared_processors(), structlog.stdlib.ExtraAdder()],
        )


class ConsoleFormatter(structlog.stdlib.ProcessorFormatter):
    """The human format: colourised columns for a developer's terminal.

    Never used on a deployed environment — ``_enforce_production_hardening``
    turns ``log_json`` on for anything that is not ``local``, because a
    delimiter-separated line is a line a caller can partly forge.
    """

    def __init__(self) -> None:
        """Build the formatter with this application's chain baked in."""
        super().__init__(
            processors=[
                *_tail_processors(),
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty(), event_key="message"),
            ],
            foreign_pre_chain=[*_shared_processors(), structlog.stdlib.ExtraAdder()],
        )


_CONFIGURED: bool = False


def _file_handler_config() -> dict[str, Any]:
    """Build the rotating-file handler's dictConfig entry, or an empty mapping.

    **Rotation exists twice, and this is the second copy.** The layer that
    actually protects the host's disk is Docker's ``json-file`` driver, capped per
    service in ``docker-compose.yml`` — because a container's stdout is written
    by the daemon, not by this process, and nothing Python does can bound a
    file it does not own.

    This handler covers the other deployment shape: a process run outside
    Docker (a script on the box, a systemd unit, a developer reproducing a
    harvest) whose output would otherwise land wherever the shell points it.
    ``LOG_FILE`` unset — which is what every container runs — leaves stdout as
    the only sink and no file to rotate.

    Returns:
        A one-entry mapping for ``dictConfig``'s ``handlers``, or ``{}``.
    """
    if not settings.log_file:
        return {}
    path = Path(settings.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "file": {
            "()": RotatingFileHandler,
            "filename": str(path),
            # Bounded on both axes: one file cannot exceed max_bytes, and the
            # set cannot exceed max_bytes * (backup_count + 1). A log that can
            # fill a disk takes the database down with it, which turns a
            # noisy day into an outage.
            "maxBytes": settings.log_file_max_bytes,
            "backupCount": settings.log_file_backup_count,
            "encoding": "utf-8",
            # Always JSON on disk: a file is read by a shipper or by grep, and
            # neither wants ANSI colour codes.
            "formatter": "json",
        }
    }


def configure_logging() -> None:
    """Configure structlog and the root logger idempotently.

    Safe to call multiple times (e.g. once per worker fork); the guard flag
    prevents duplicate handler registration that would otherwise double every
    log line.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = "json" if settings.log_json else "console"
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": formatter,
            "stream": sys.stdout,
        },
        **_file_handler_config(),
    }

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": f"{__name__}.JsonFormatter"},
                "console": {"()": f"{__name__}.ConsoleFormatter"},
            },
            "handlers": handlers,
            "root": {
                "level": settings.log_level.upper(),
                "handlers": list(handlers),
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

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_shared_processors(),
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Hands the event dict to the ProcessorFormatter on the handler
            # rather than rendering here, which is what puts structlog's own
            # events and stdlib's through the same final chain.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def reset_logging_configuration() -> None:
    """Forget that logging was configured, so the next call rebuilds it.

    For tests that change settings — the log format, the file sink — and need
    the next :func:`configure_logging` to act on them. Production never calls
    this; the guard flag exists precisely so that a re-forked worker does not.
    """
    global _CONFIGURED
    _CONFIGURED = False


#: Uvicorn's own loggers. It installs handlers on these when the server starts,
#: which is AFTER this module has configured the root logger — so left alone
#: they keep emitting uvicorn's plain-text format.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

#: Celery's equivalents. Celery hijacks the root logger on worker startup, and
#: the same argument applies: a worker's own lines are exactly what is being
#: read when a harvest failed, and a shipper that cannot parse them files them
#: as unparseable. ``worker_hijack_root_logger=False`` in the Celery config is
#: the other half of this — see :mod:`src.core.celery_app`.
_CELERY_LOGGERS = ("celery", "celery.app.trace", "celery.worker", "celery.beat")


def adopt_uvicorn_loggers() -> None:
    """Make uvicorn's own lines go through our formatter too.

    Called from the application lifespan, which is the only moment that works.
    Uvicorn configures logging inside `Server.serve()` — after this module's
    `configure_logging()` has run at import time, and before the lifespan
    starts — so anything done earlier is simply overwritten.

    Why it matters more than tidiness: "one JSON object per line" is a claim a
    log shipper relies on, and it is either true of every line or it is not a
    claim. Leaving uvicorn's startup, shutdown and error lines in plain text
    means a parser drops them or files them as unparseable — and they are
    exactly the lines that matter when a container will not come up.

    Removing the handlers rather than reformatting them: with `propagate` on,
    the records reach the root handler this module already configured, so there
    is one formatter to keep correct instead of two.

    **Two lines per container start are still plain**, and they are the two this
    cannot reach: `Started server process` and `Waiting for application startup`
    are emitted before the lifespan exists to run anything. Covering them would
    mean handing uvicorn a `--log-config` file, which cannot express the
    text-or-JSON switch this module makes from settings — a static file would
    force JSON on a developer's terminal too. Neither line carries information,
    so the trade is two unparseable lines per restart against a worse format
    locally, and the noise wins.
    """
    _adopt(_UVICORN_LOGGERS)


def adopt_celery_loggers() -> None:
    """Make Celery's own lines go through our formatter too.

    The worker's counterpart to :func:`adopt_uvicorn_loggers`, called from the
    ``setup_logging`` signal — which Celery fires *instead of* configuring
    logging itself, so connecting to it is what stops the hijack rather than
    undoing it afterwards.
    """
    _adopt(_CELERY_LOGGERS)


def _adopt(names: tuple[str, ...]) -> None:
    """Strip a library's own handlers and let its records reach the root."""
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced stdlib logger, configuring logging on first use.

    The %-style entry point, and what nearly every call site in this codebase
    uses. Its records go through the same structlog chain as
    :func:`get_struct_logger`'s — including the redaction processor — because
    the chain lives on the handler rather than on the logger.
    """
    configure_logging()
    return logging.getLogger(name)


def get_struct_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a namespaced structlog logger, configuring logging on first use.

    The key-value entry point, for events an alert or a dashboard will bind to:
    ``log.warning("harvest partial", source="funnel", missing=3)`` puts
    ``source`` and ``missing`` in the line as fields, where a Loki query can
    filter on them, instead of inside a sentence it would have to parse.
    """
    configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = [
    "ConsoleFormatter",
    "JsonFormatter",
    "adopt_celery_loggers",
    "adopt_uvicorn_loggers",
    "configure_logging",
    "get_logger",
    "get_struct_logger",
    "reset_logging_configuration",
]
