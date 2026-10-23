"""Open the diagnostic workspace's main pages on the code that was just deployed.

The deploy's own health checks prove the containers are up and nginx answers
200 — and on 2026-09-29 both were true for three hours while every SKU card
answered 500. `/health` touches no tenant data, and the failure lived in how a
real row from before a migration was turned into a response. The only probe that
sees that class of bug is one that reads real rows through the real service.

So this does, for each main page, with what the SPA asks for when the page first
opens, and serialises every answer the way a response is (``scripts/smoke/``):

* Monitoring — the SKU list, and the three busiest SKU cards;
* P&L — the period list, the per-SKU report for the default week, the stock balance;
* Heatmap — the grid and its catalogue, for the default thirty days;
* A/B tests — the list, and the newest test.

Only for the one workspace a diagnostic may read: the session is
`diagnostic_session()` — read-only at the transaction level and pinned to
it by row-level security — so the rows below are that workspace's and
nobody else's. It prints counts and status, never figures.

Read-only is enforced, not intended, which decides two things. A page whose read
would write is not opened: the P&L report over a stale settlement rollup is
reported as **skipped**, by name, on stdout — not passed, and not failed, since a
stale rollup is the ordinary state after a harvest. And each page runs under its
own savepoint, so a page that breaks the transaction does not take every page
after it down too and hide which one it was.

Meant to run right after a deploy, inside the freshly rotated api container. A
non-zero exit should stop the rollout before worker and beat are updated; it
does NOT roll back —
that is a human's call (scripts/deploy/rollback.sh). Exit 3 means it could not
check at all — no cards to open — and still fails, because a guard that skips
itself must not look like a pass.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from src.core.diagnostics import diagnostic_session, diagnostic_workspace

if not __package__:
    # A deploy runs this by PATH (`python /app/scripts/smoke_after_deploy.py`),
    # and that puts scripts/ itself on the import path rather than the backend
    # root, so `scripts.smoke` would not resolve and every deploy would fail on
    # a ModuleNotFoundError. This is the root `python -m` from /app would add.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.smoke import SmokeReport, smoke

#: The whole probe must finish well inside the deploy job's own timeout.
TIMEOUT_SECONDS = 120

EXIT_BROKEN = 1
EXIT_CANNOT_CHECK = 3


def verdict(report: SmokeReport) -> int:
    """Print what the probe found and turn it into the exit code the deploy reads."""
    for skipped in report.skipped:
        print(f"smoke: skipped {skipped}")
    if report.failures:
        for failure in report.failures:
            print(f"smoke: FAILED {failure}", file=sys.stderr)
        return EXIT_BROKEN
    if not report.cards:
        print("smoke: no cards with recent orders to open; nothing was checked", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    rows = ", ".join(f"{page} {count}" for page, count in report.rendered.items())
    print(f"smoke: ok — rendered (rows): {rows}")
    return 0


async def _run() -> int:
    async with diagnostic_session() as session:
        report = await smoke(session, workspace_id=diagnostic_workspace())
    return verdict(report)


def main() -> int:
    """Run the probe under a hard ceiling; a hang is a failure, not a pass."""
    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=TIMEOUT_SECONDS))
    except TimeoutError:
        print(f"smoke: FAILED no answer in {TIMEOUT_SECONDS}s", file=sys.stderr)
        return EXIT_BROKEN


if __name__ == "__main__":
    raise SystemExit(main())
