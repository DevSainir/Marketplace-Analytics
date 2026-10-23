"""Run a probe against production data, behind the diagnostic gate.

The sanctioned way to look at live rows. It executes the file it is given with
one name pre-bound — ``session``, already read-only and already pinned to the
one workspace diagnostics may read — and nothing else. A probe that opens its own
session is not using this script, and that is the thing to notice in review.

In production, copy the probe into the worker container and run it there::

    docker cp probe.py marketplace-analytics-worker-1:/app/
    docker exec marketplace-analytics-worker-1 /app/.venv/bin/python \
      /app/scripts/diagnose.py /app/probe.py

The probe itself is a plain async body, written as if it were the inside of a
function::

    rows = (await session.execute(select(func.count()).select_from(Card))).scalar_one()
    print(rows)

Why a runner rather than a helper the probe imports: a helper is one import away
from being replaced by ``AsyncSessionLocal`` when it gets in the way, and the
worker runs as the table owner, so replacing it silently restores the full reach
of the fleet. Here the session is handed in already constrained.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import textwrap

from src.core.diagnostics import diagnostic_session, diagnostic_workspace


async def _run(source: str) -> None:
    """Execute the probe body inside the gate."""
    body = textwrap.indent(source, "    ")
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - the input is a local file the operator wrote
        f"async def _probe(session):\n{body or '    pass'}",
        namespace,
    )
    probe = namespace["_probe"]
    async with diagnostic_session() as session:
        await probe(session)  # type: ignore[operator]


def main() -> int:
    """Read the probe file named on the command line and run it."""
    if len(sys.argv) != 2:
        print("usage: diagnose.py <probe.py>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    if not path.is_file():
        print(f"no such probe: {path}", file=sys.stderr)
        return 2
    print(f"# workspace {diagnostic_workspace()} — read-only", file=sys.stderr)
    asyncio.run(_run(path.read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
