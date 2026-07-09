"""One-off database seed.

Runs the same "harvest everything" logic the nightly Celery Beat job uses:
discover all account SKUs from the Content API, then harvest the last 7 days of
funnel + stock (per SKU) and advertising (all active/paused campaigns).

Run from the ``backend`` directory (``.env`` populated)::

    python -m scripts.seed_harvest
"""

from __future__ import annotations

import asyncio

from src.modules.monitoring.tasks import _discover_and_harvest


async def main() -> None:
    """Seed a 7-day, all-category, all-SKU harvest."""
    result = await _discover_and_harvest(days=7)
    print(
        f"Seed complete: funnel={result['funnel_rows']} "
        f"advertising={result['advertising_rows']} stock={result['stock_rows']} "
        f"product_cards={result['product_card_rows']} "
        f"product_sizes={result['product_size_rows']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
