"""One-off database seed.

Runs the same "harvest everything" logic the nightly Celery Beat job uses:
for every workspace with WB tokens stored in the database, discover its SKUs
from the Content API, then harvest the last 7 days of funnel + stock (per SKU)
and advertising (all active/paused campaigns).

Run from the ``backend`` directory (``.env`` populated, migrations applied)::

    python -m scripts.seed_harvest
"""

from __future__ import annotations

import asyncio

from src.modules.monitoring.tasks.discovery import _discover_and_harvest


async def main() -> None:
    """Seed a 7-day, all-workspace, all-SKU harvest."""
    result = await _discover_and_harvest(days=7)
    counts = ", ".join(f"{key}={value}" for key, value in sorted(result.items()))
    print(f"Seed complete: {counts}")


if __name__ == "__main__":
    asyncio.run(main())
