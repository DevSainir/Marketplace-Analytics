"""Live smoke-test for the WildBerries integration.

Runs from the safest checks to the most specific so a bad token or a wrong
contract fails loudly and early, without needing a database or the full app:

    1. ``GET /ping`` on both WB hosts  -> proves connectivity + auth per surface.
    2. ``GET /adv/v1/promotion/count`` -> lists real campaigns (advertising
       token), and hands us a real ``campaign_id`` to test fullstats with.
    3. Our ``WBAnalyticsClient`` funnel + stocks calls (needs ``--nm-ids``).
    4. Our ``WBAdvertisingClient`` fullstats call (auto-picks a campaign).

Every step prints the HTTP status and a raw JSON preview and never aborts the
whole run on a single failure — the point is to observe reality and reconcile
the contracts in ``client.py`` / ``schemas.py``.

Usage (from the ``backend`` directory, with ``.env`` populated)::

    python -m scripts.wb_smoke                          # ping + campaign list
    python -m scripts.wb_smoke --nm-ids 123456,234567   # + funnel + stocks
    python -m scripts.wb_smoke --nm-ids 123456 --campaign-id 987654
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from typing import Any

import httpx

from src.core.config import settings

_PREVIEW_CHARS = 1200


def _preview(payload: Any) -> str:
    """Return a truncated, pretty JSON preview of an arbitrary payload."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if len(text) > _PREVIEW_CHARS:
        return text[:_PREVIEW_CHARS] + f"\n… (+{len(text) - _PREVIEW_CHARS} chars)"
    return text


def _banner(title: str) -> None:
    """Print a section header."""
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


async def _ping(name: str, base_url: str, token: str) -> None:
    """Hit ``GET /ping`` on a WB host to validate connectivity + token."""
    _banner(f"[1] PING {name}: {base_url}/ping")
    if not token:
        print("  SKIP: token is empty in .env")
        return
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            resp = await client.get("/ping", headers={"Authorization": token})
        print(f"  HTTP {resp.status_code}")
        try:
            print(_preview(resp.json()))
        except json.JSONDecodeError:
            print(f"  (non-JSON body) {resp.text[:200]!r}")
    except httpx.HTTPError as exc:
        print(f"  TRANSPORT ERROR: {exc!r}")


async def _list_campaigns() -> int | None:
    """List advertising campaigns; return the first campaign id if any.

    Endpoint: ``GET /adv/v1/promotion/count`` (no params, lists everything).
    """
    _banner("[2] ADVERTISING campaigns: GET /adv/v1/promotion/count")
    if not settings.wb_advertising_token:
        print("  SKIP: WB_ADVERTISING_TOKEN is empty")
        return None
    try:
        async with httpx.AsyncClient(
            base_url=settings.wb_advertising_base_url, timeout=20
        ) as client:
            resp = await client.get(
                "/adv/v1/promotion/count",
                headers={"Authorization": settings.wb_advertising_token},
            )
        print(f"  HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"  body: {resp.text[:300]!r}")
            return None
        data = resp.json()
        print(_preview(data))
        # Response shape: {"adverts": [{"type":.., "advert_list":[{"advertId":..}]}]}
        for group in data.get("adverts") or []:
            for advert in group.get("advert_list") or []:
                found = advert.get("advertId")
                if found is not None:
                    print(f"\n  -> picked campaign_id={found} for fullstats test")
                    return int(found)
        print("  (no campaigns found on this account)")
        return None
    except httpx.HTTPError as exc:
        print(f"  TRANSPORT ERROR: {exc!r}")
        return None


async def _test_funnel_and_stocks(nm_ids: list[int]) -> None:
    """Exercise our WBAnalyticsClient against the real API."""
    from src.integrations.wildberries import WBAnalyticsClient

    end = date.today()
    start = end - timedelta(days=7)

    _banner(f"[3a] FUNNEL via WBAnalyticsClient (nm_ids={nm_ids}, {start}..{end})")
    try:
        async with WBAnalyticsClient(settings) as client:
            rows = await client.fetch_sales_funnel(nm_ids=nm_ids, date_from=start, date_to=end)
        print(f"  OK: parsed {len(rows)} funnel rows")
        if rows:
            print(_preview(rows[0].model_dump()))
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    _banner(f"[3b] STOCKS via WBAnalyticsClient (nm_ids={nm_ids})")
    try:
        async with WBAnalyticsClient(settings) as client:
            rows = await client.fetch_warehouse_stocks(nm_ids=nm_ids)
        print(f"  OK: parsed {len(rows)} stock rows")
        if rows:
            print(_preview(rows[0].model_dump()))
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")


async def _test_fullstats(campaign_id: int) -> None:
    """Exercise our WBAdvertisingClient against the real API."""
    from src.integrations.wildberries import WBAdvertisingClient

    end = date.today()
    start = end - timedelta(days=7)
    _banner(f"[4] FULLSTATS via WBAdvertisingClient (campaign_id={campaign_id})")
    try:
        async with WBAdvertisingClient(settings) as client:
            stats_list = await client.fetch_full_stats(
                campaign_ids=[campaign_id], date_from=start, date_to=end
            )
        if stats_list:
            stats = stats_list[0]
            print(f"  OK: parsed campaign {stats.campaign_id}, {len(stats.days)} days")
            print(_preview(stats.model_dump()))
        else:
            print("  OK: no data returned for this campaign/window")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")


async def main(nm_ids: list[int], campaign_id: int | None) -> None:
    """Run the smoke-test pipeline end to end."""
    await _ping("analytics", settings.wb_analytics_base_url, settings.wb_analytics_token)
    await _ping(
        "advertising",
        settings.wb_advertising_base_url,
        settings.wb_advertising_token,
    )

    discovered = await _list_campaigns()

    if nm_ids:
        await _test_funnel_and_stocks(nm_ids)
    else:
        _banner("[3] FUNNEL + STOCKS skipped")
        print("  pass --nm-ids 123456,234567 to test these (needs real SKUs)")

    target_campaign = campaign_id or discovered
    if target_campaign is not None:
        await _test_fullstats(target_campaign)
    else:
        _banner("[4] FULLSTATS skipped")
        print("  no campaign id (none discovered, none passed via --campaign-id)")


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="WildBerries API smoke test.")
    parser.add_argument(
        "--nm-ids",
        default="",
        help="Comma-separated SKU ids to test funnel/stocks (e.g. 123,456).",
    )
    parser.add_argument(
        "--campaign-id",
        type=int,
        default=None,
        help="Explicit advertising campaign id for fullstats.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    parsed_nm_ids = [int(x) for x in args.nm_ids.split(",") if x.strip()]
    asyncio.run(main(parsed_nm_ids, args.campaign_id))
