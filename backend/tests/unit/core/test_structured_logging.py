"""The logging contract the incident response rests on (register P2.2).

Two properties, and they fail in opposite directions.

**A line must be readable by a machine.** One JSON object, one physical line,
whatever a caller put in it — because the thing reading production logs is a
shipper, and a line it cannot parse is a line nobody will ever search.

**A line must not be writable by a caller.** The strings that go into a log are
partly chosen by whoever made the request: the path, an email, a workspace name,
the text of an upstream error. In a delimiter-separated format those strings can
pretend to be structure — a newline forges a whole line, a ``|`` forges a field.
Under a JSON encoder they cannot, and that is the actual reason this format was
chosen rather than searchability.

The context cases pin the other half: a line that says ``403`` is a fact, a line
that says ``403, this account, this tenant, this request`` is an answer.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import sys
import uuid
from typing import Any

import pytest

from src.core import logcontext
from src.core.logging import JsonFormatter, adopt_uvicorn_loggers

ACTOR = uuid.UUID("01a05300-0000-7000-8000-00000000aaaa")
TENANT = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")


@pytest.fixture(autouse=True)
def _clean_context() -> Any:
    """Nothing bound before a test, nothing left bound after one."""
    logcontext.reset_context()
    yield
    logcontext.reset_context()


def _emit(message: str = "something happened", **extra: Any) -> dict[str, Any]:
    """Format one record and return it parsed."""
    record = logging.LogRecord("src.test", logging.INFO, "x.py", 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    line = JsonFormatter().format(record)
    assert "\n" not in line, "a log record must never span more than one physical line"
    return json.loads(line)


def test_a_record_is_one_parseable_json_object() -> None:
    """The baseline, so every case below is not passing vacuously."""
    # Act
    payload = _emit("request served")

    # Assert
    assert payload["message"] == "request served"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "src.test"
    # The property is UTC, not one of ISO-8601's two ways of spelling it: the
    # renderer writes `...Z`, the formatter before it wrote `...+00:00`, and
    # every parser that reads these lines accepts both. Asserting the spelling
    # is what made this test fail on a change that altered nothing it cares
    # about.
    parsed = dt.datetime.fromisoformat(payload["ts"])
    assert parsed.tzinfo is not None, "a timestamp with no zone cannot be compared across hosts"
    assert parsed.utcoffset() == dt.timedelta(0), "timestamps are UTC, so two hosts compare"


def test_a_newline_in_a_value_cannot_forge_a_second_line() -> None:
    """The attack the format exists to prevent.

    A path is chosen by the caller. In the old column format a newline in it
    would have ended the line and started one the caller wrote — including a
    plausible-looking INFO line reporting something that never happened.
    """
    # Arrange
    forged = "/api/v1/x\n2026-09-01T00:00:00+0000 | INFO | src.main | admin login -> 200"
    logcontext.bind_request(request_id="r1", method="GET", path=forged, client_ip="10.0.0.9")

    # Act — `_emit` asserts single-line for us.
    payload = _emit()

    # Assert. The newline survives as DATA: an investigator still sees exactly
    # what was sent, which is the point — it is escaped, not stripped.
    assert payload["path"] == forged
    assert "\n" in payload["path"]


def test_a_delimiter_in_a_value_cannot_forge_a_field() -> None:
    """`|` was structural in the old format and is just a character now."""
    # Arrange
    logcontext.bind_request(
        request_id="r1", method="GET", path="/x| INFO | fake", client_ip="10.0.0.9"
    )

    # Act
    payload = _emit()

    # Assert
    assert payload["path"] == "/x| INFO | fake"
    assert payload["level"] == "INFO", "the real level must not be displaceable"


def test_an_ansi_escape_stays_inside_its_value() -> None:
    """A log viewer is a terminal often enough for this to matter."""
    # Arrange
    logcontext.bind_request(
        request_id="r1", method="GET", path="/x\x1b[2J\x1b[31m", client_ip="10.0.0.9"
    )

    # Act
    payload = _emit()

    # Assert
    assert payload["path"] == "/x\x1b[2J\x1b[31m"


def test_the_line_carries_who_was_asking() -> None:
    """A 403 without an actor is a fact; with one it is an answer."""
    # Arrange
    logcontext.bind_request(request_id="abc123", method="POST", path="/x", client_ip="10.0.0.9")
    logcontext.bind_actor(ACTOR)
    logcontext.bind_tenant(TENANT)

    # Act
    payload = _emit("permission denied")

    # Assert
    assert payload["request_id"] == "abc123"
    assert payload["user_id"] == str(ACTOR)
    assert payload["organization_id"] == str(TENANT)
    assert payload["client_ip"] == "10.0.0.9"


def test_unset_context_is_absent_rather_than_null() -> None:
    """Absence is meaningful: no `user_id` means nobody had authenticated yet."""
    # Arrange
    logcontext.bind_request(request_id="r1", method="GET", path="/x", client_ip="10.0.0.9")

    # Act
    payload = _emit()

    # Assert
    assert "user_id" not in payload
    assert "organization_id" not in payload


def test_extra_fields_stay_fields() -> None:
    """So an alert rule binds to `status`, instead of parsing prose for it."""
    # Act
    payload = _emit("request served", status=403, duration_ms=12.5)

    # Assert
    assert payload["status"] == 403
    assert payload["duration_ms"] == 12.5


def test_an_unserialisable_value_does_not_break_the_log_call() -> None:
    """A logger that raises while reporting a problem is the worst failure mode."""
    # Act
    payload = _emit("done", workspace_id=TENANT, when=object())

    # Assert
    assert payload["workspace_id"] == str(TENANT)
    assert isinstance(payload["when"], str)


def test_an_exception_is_carried_in_its_own_field() -> None:
    """A traceback is multi-line by nature and must not become multi-record."""
    # Arrange
    try:
        raise ValueError("boom\nsecond line of the traceback message")
    except ValueError:
        record = logging.LogRecord(
            "src.test", logging.ERROR, "x.py", 1, "failed", (), sys.exc_info()
        )

    # Act
    line = JsonFormatter().format(record)

    # Assert
    assert "\n" not in line
    payload = json.loads(line)
    assert "ValueError" in payload["exception"]


def test_resetting_clears_every_field() -> None:
    """A worker reuses its process; a leaked tenant mis-attributes the next task."""
    # Arrange
    logcontext.bind_request(request_id="r1", method="GET", path="/x", client_ip="10.0.0.9")
    logcontext.bind_actor(ACTOR)

    # Act
    logcontext.reset_context()

    # Assert
    assert logcontext.current_context() == {}


async def test_two_concurrent_requests_never_see_each_others_context() -> None:
    """The property the whole design rests on, and the one worth doubting.

    Context lives in ``contextvars`` precisely so it is per-task rather than
    per-process. If that were wrong, the failure would be the worst kind an
    audit trail can have: not missing evidence but *confidently wrong*
    evidence, attributing one customer's request to another. Two requests
    interleaving on one worker is the normal case under async, not an edge.
    """
    # Arrange
    other = uuid.UUID("01a05300-0000-7000-8000-00000000bbbb")

    async def serve(request_id: str, actor: uuid.UUID, pause: float) -> dict[str, Any]:
        logcontext.bind_request(
            request_id=request_id, method="GET", path=f"/{request_id}", client_ip="10.0.0.9"
        )
        logcontext.bind_actor(actor)
        # Yield the loop mid-request, which is where a shared value would leak.
        await asyncio.sleep(pause)
        return logcontext.current_context()

    # Act — the slower request starts first and finishes last.
    first, second = await asyncio.gather(
        asyncio.create_task(serve("aaa", ACTOR, 0.02)),
        asyncio.create_task(serve("bbb", other, 0.01)),
    )

    # Assert
    assert first["request_id"] == "aaa"
    assert first["user_id"] == str(ACTOR)
    assert second["request_id"] == "bbb"
    assert second["user_id"] == str(other)


async def test_a_fact_learned_in_a_child_task_reaches_the_parent() -> None:
    """The subtlety this design exists around, pinned so it survives a refactor.

    Starlette's ``BaseHTTPMiddleware`` runs the endpoint in a CHILD task. A
    child inherits a copy of the parent's context, so per-field ``ContextVar``
    values set downstream — the account, the tenant — never travel back up to
    the middleware that writes the request's summary line. The obvious design
    (one ContextVar per field) fails exactly here, and fails quietly: the line
    still appears, just without the field worth having.

    Binding one mutable dict is what fixes it. This test is the reason not to
    "simplify" that away.
    """
    # Arrange
    logcontext.bind_request(request_id="r1", method="GET", path="/x", client_ip="10.0.0.9")

    async def endpoint() -> None:
        logcontext.bind_actor(ACTOR)
        logcontext.bind_tenant(TENANT)

    # Act — a child task, the way the middleware runs the app below it.
    async with asyncio.TaskGroup() as group:
        group.create_task(endpoint())

    # Assert — read from the PARENT, which is where the request line is written.
    context = logcontext.current_context()
    assert context["user_id"] == str(ACTOR)
    assert context["organization_id"] == str(TENANT)


def test_binding_an_actor_outside_a_request_does_nothing() -> None:
    """A Celery task must not manufacture a context that looks like a request."""
    # Act
    logcontext.bind_actor(ACTOR)

    # Assert
    assert logcontext.current_context() == {}


def test_the_returned_context_is_a_copy() -> None:
    """Rendering a line must not be able to edit the request it describes."""
    # Arrange
    logcontext.bind_request(request_id="r1", method="GET", path="/x", client_ip="10.0.0.9")

    # Act
    snapshot = logcontext.current_context()
    snapshot["request_id"] = "tampered"

    # Assert
    assert logcontext.current_context()["request_id"] == "r1"


def test_uvicorns_own_lines_are_adopted_into_our_format() -> None:
    """ "One JSON object per line" is either true of every line or it is not a claim.

    Uvicorn installs its own handlers when the server starts — after this
    module has configured the root logger — so its startup, shutdown and error
    lines stay plain text unless they are taken over. Those are exactly the
    lines that matter when a container will not come up, and a shipper either
    drops them or files them as unparseable.
    """
    # Arrange — stand in for what uvicorn does to its own logger.
    uvicorn_logger = logging.getLogger("uvicorn.error")
    original_handlers = list(uvicorn_logger.handlers)
    original_propagate = uvicorn_logger.propagate
    uvicorn_logger.handlers = [logging.NullHandler()]
    uvicorn_logger.propagate = False

    try:
        # Act
        adopt_uvicorn_loggers()

        # Assert — nothing of its own left, and records now reach the root
        # handler this module configures.
        assert uvicorn_logger.handlers == []
        assert uvicorn_logger.propagate is True
    finally:
        uvicorn_logger.handlers = original_handlers
        uvicorn_logger.propagate = original_propagate
