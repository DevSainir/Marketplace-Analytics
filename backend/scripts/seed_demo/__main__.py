"""Fill a demo database with the fabricated shop — what `make demo` runs.

Usage, inside the demo stack (the Makefile does this)::

    docker compose ... exec -T api python -m scripts.seed_demo

Safe to re-run: it empties the database and writes everything again, re-dated
so the newest day is yesterday. It refuses outright on anything but a local
database holding only the demo — see :mod:`scripts.seed_demo.tenancy`.
"""

from __future__ import annotations

import asyncio
import sys

from scripts.seed_demo.extras import mark_settlement_fresh
from scripts.seed_demo.shop import populate_workspace
from scripts.seed_demo.tenancy import (
    DEMO_EMAIL,
    DEMO_WORKSPACE,
    NotADemoDatabaseError,
    assert_demo_database,
    create_identity,
    empty_database,
)
from src.core.database import AsyncSessionLocal, engine
from src.core.timeutils import moscow_today


async def seed() -> dict[str, int]:
    """Empty the demo database and write the demo into it, in one transaction."""
    async with AsyncSessionLocal() as session:
        await assert_demo_database(session)
        await empty_database(session)
        workspace_id = await create_identity(session)
        written = await populate_workspace(session, workspace_id, moscow_today())
        await session.commit()
    await mark_settlement_fresh(workspace_id)
    return written


async def main() -> int:
    """Seed, print what was written, and return the process exit code."""
    try:
        written = await seed()
    except NotADemoDatabaseError as refused:
        print(f"Refusing to seed the demo: {refused}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    summary = ", ".join(f"{area} {rows}" for area, rows in written.items())
    print(f'Demo data written to workspace "{DEMO_WORKSPACE}" for {DEMO_EMAIL}: {summary} rows.')
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
