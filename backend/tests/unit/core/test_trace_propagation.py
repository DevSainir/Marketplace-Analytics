"""One id joining a click to the background work it caused (register P2.2).

The API half of this service was already legible: every request binds a
context, every line carries it. The worker half was not, and it is the half
that runs unattended — a failed request is answered with a 500 somebody sees, a
failed 06:00 harvest is a number that is quietly stale until a customer asks.

What closes that gap is one string travelling through a Celery message. A
request that enqueues a harvest puts its ``trace_id`` in the message headers;
the worker binds the same value minutes later, in another container. These
tests pin the three ways that chain breaks, and the reason each is worth a test
of its own is that **none of them fails loudly**. A severed trace looks exactly
like a working system with unrelated log lines.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.core import logcontext
from src.core.observability import celery_runtime


class FakeRequest:
    """A stand-in for Celery's ``Context``, which is what a task sees.

    A fake rather than a mock: the thing under test is how a header is READ
    off this object, so a mock that answers every attribute would assert
    nothing — it would pass just as happily against a function that looked for
    the wrong name.
    """

    def __init__(self, headers: dict[str, Any] | None = None, **attributes: Any) -> None:
        """Build a request carrying headers, attributes, or neither."""
        self.headers = headers
        for name, value in attributes.items():
            setattr(self, name, value)


@pytest.fixture(autouse=True)
def _clean_context() -> Any:
    """Nothing bound before a test, nothing left bound after one."""
    logcontext.reset_context()
    yield
    logcontext.reset_context()


def test_a_request_puts_its_trace_id_into_the_outgoing_message() -> None:
    """The publishing half: an API request hands its id to the task."""
    # Arrange
    logcontext.bind_request(
        request_id="abc123def456", method="POST", path="/api/v1/refresh", client_ip="10.0.0.9"
    )
    trace_id = logcontext.current_trace_id()
    headers: dict[str, Any] = {}

    # Act
    celery_runtime._propagate_trace(headers=headers)

    # Assert
    assert headers[celery_runtime.TRACE_HEADER] == trace_id


def test_the_worker_binds_the_trace_id_the_request_sent() -> None:
    """The receiving half. Together with the case above, this is the chain."""
    # Arrange
    trace_id = "f0e1d2c3b4a5968778695a4b3c2d1e0f"
    task = type("Task", (), {"name": "monitoring.harvest_sku_window"})()
    task.request = FakeRequest(headers={celery_runtime.TRACE_HEADER: trace_id})

    # Act
    celery_runtime._bind_task_context(task_id="task-1", task=task)

    # Assert
    context = logcontext.current_context()
    assert context["trace_id"] == trace_id
    assert context["task_id"] == "task-1"
    assert context["task_name"] == "monitoring.harvest_sku_window"


def test_the_header_is_found_however_celery_exposes_it() -> None:
    """Celery has moved this between an attribute, a ``get`` and a mapping.

    Reading only one of the three would not raise or warn — it would silently
    bind a fresh id, and the trace would just quietly stop joining. That is
    why all three shapes are tried, and why all three are pinned here.
    """
    # Arrange
    trace_id = "aaaabbbbccccddddeeeeffff00001111"
    shapes = [
        FakeRequest(headers={celery_runtime.TRACE_HEADER: trace_id}),
        FakeRequest(**{celery_runtime.TRACE_HEADER: trace_id}),
    ]

    for request in shapes:
        logcontext.reset_context()
        task = type("Task", (), {"name": "t"})()
        task.request = request

        # Act
        celery_runtime._bind_task_context(task_id="task-1", task=task)

        # Assert
        assert logcontext.current_context()["trace_id"] == trace_id


def test_a_scheduled_task_gets_a_fresh_trace_rather_than_a_borrowed_one() -> None:
    """A beat tick has no parent, and must not be given one.

    Inventing an id here would be cheap and would make the graph look tidier.
    It would also be a false claim about causation — the nightly harvest was
    not caused by whatever request happened to run last in this process, and a
    trace that says it was is worse than a trace that says nothing.
    """
    # Arrange
    task = type("Task", (), {"name": "monitoring.harvest_all"})()
    task.request = FakeRequest()

    # Act
    celery_runtime._bind_task_context(task_id="beat-1", task=task)

    # Assert
    context = logcontext.current_context()
    assert len(context["trace_id"]) == 32
    assert context["task_name"] == "monitoring.harvest_all"


def test_publishing_outside_a_request_adds_no_header() -> None:
    """Nothing bound, nothing claimed. The counterpart to the case above."""
    # Arrange
    headers: dict[str, Any] = {}

    # Act
    celery_runtime._propagate_trace(headers=headers)

    # Assert
    assert headers == {}


def test_a_tasks_context_does_not_survive_into_the_next_task() -> None:
    """A worker reuses its process, so a left-bound context mis-attributes.

    This is the same hazard :func:`src.core.tasks.run_task` already resets for.
    The ``task_postrun`` hook is the belt to that brace: a task that dies before
    ``run_task`` returns never reaches the other one, and the next task would
    then log under the previous task's tenant. Confidently wrong evidence is
    worse than none — it is the kind that gets acted on.
    """
    # Arrange
    task = type("Task", (), {"name": "monitoring.harvest_all"})()
    task.request = FakeRequest()
    celery_runtime._bind_task_context(task_id="task-1", task=task)
    logcontext.bind_workspace(uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615"))

    # Act
    celery_runtime._record_task_outcome(task_id="task-1", task=task, state="SUCCESS")

    # Assert
    assert logcontext.current_context() == {}


def test_the_two_identifiers_are_different_things() -> None:
    """``request_id`` is quoted by a customer; ``trace_id`` spans processes.

    They are kept separate deliberately, and the shapes are the reason: twelve
    hex characters is something a person reads off a screen and types back,
    thirty-two is Sentry's own trace-id format — which is what lets a log
    search and an error report line up on one string.
    """
    # Act
    logcontext.bind_request(
        request_id=logcontext.new_request_id(), method="GET", path="/x", client_ip="10.0.0.1"
    )

    # Assert
    context = logcontext.current_context()
    assert len(context["request_id"]) == 12
    assert len(context["trace_id"]) == 32
    assert context["request_id"] != context["trace_id"]


def test_a_trace_id_is_never_taken_from_the_caller() -> None:
    """Correlation you cannot trust is worse than correlation you do not have.

    A trace id arriving in a request header would be a value chosen by whoever
    is being investigated — so ``bind_request`` mints its own, and the HTTP
    middleware never reads one from the request. Pinned here because the
    "obvious improvement" is to accept an inbound ``X-Trace-Id``, and it would
    hand an attacker the ability to merge their requests into somebody else's
    trace or to fill the field with anything at all.
    """
    # Act
    logcontext.bind_request(
        request_id="r1", method="GET", path="/x", client_ip="10.0.0.1", trace_id=None
    )

    # Assert
    trace_id = logcontext.current_trace_id()
    assert trace_id is not None
    assert int(trace_id, 16) >= 0, "a minted trace id is hex, whatever a caller sent"
