"""What one run of the smoke probe found, and the one way a page is opened.

Every page goes through :func:`attempt`, so every page fails the same way: the
exception is written down as ``"<what>: <ExcType>: <message>"`` and the run goes
on to the next page. A run that stopped at the first broken page would name one
page and hide the state of the rest, and the rest is what decides how bad the
deploy is. A page that decides not to open raises :class:`PageSkipped`, and is
recorded as skipped with its reason — neither a pass nor a failure.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession


class PageSkipped(Exception):  # noqa: N818 - a verdict, not an error
    """Raised by a page that chose not to open, with the reason as its message."""


@dataclass
class SmokeReport:
    """The outcome of one probe — counts and names only, never a figure.

    Attributes:
        cards: The SKU cards picked to open, busiest first. Empty means the
            probe had nothing to check, which the entrypoint fails on.
        rendered: Per page, how many rows it rendered. The count is what shows
            the page ran on real rows rather than on an empty кабинет.
        skipped: Pages deliberately not opened, each with the reason. Printed,
            so a page that was not checked never reads as one that passed.
        failures: ``"<what>: <ExcType>: <message>"`` per page that broke.
    """

    cards: list[int] = field(default_factory=list)
    rendered: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


async def attempt(
    session: AsyncSession,
    report: SmokeReport,
    what: str,
    render: Callable[[], Awaitable[int]],
    *,
    tally: str | None = None,
) -> bool:
    """Open one page under its own savepoint and record how it went.

    The savepoint is what keeps one failure one failure. A page that dies on a
    database error — a column the code reads and the migration did not add —
    aborts the whole transaction, and without it every page after that one
    would fail too, with ``InFailedSqlTransaction``, burying the page that
    actually broke under a list of pages that did not. Savepoints are allowed
    in a read-only transaction, and rolling back to one keeps the gate's role
    and tenant, which were set before it.

    Args:
        session: The probe's session.
        report: Where the outcome is written.
        what: The page's name in the output.
        render: Opens the page, serialises the answer, returns its row count;
            or raises :class:`PageSkipped` to say why it did not open it.
        tally: Where the count is added up instead of under ``what`` — the
            cards are one line of output, not three.

    Returns:
        Whether the page rendered.
    """
    try:
        async with session.begin_nested():
            count = await render()
    except PageSkipped as skip:
        report.skipped.append(f"{what}: {skip}")
        return False
    except Exception as exc:  # every failure is the finding
        report.failures.append(f"{what}: {type(exc).__name__}: {exc}")
        return False
    key = tally or what
    report.rendered[key] = report.rendered.get(key, 0) + count
    return True


__all__ = ["PageSkipped", "SmokeReport", "attempt"]
