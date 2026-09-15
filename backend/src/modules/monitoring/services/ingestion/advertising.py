"""Ingestion of the advertising fact family (fullstats, campaigns, search zone)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.core.logging import get_logger
from src.core.timeutils import MOSCOW_TZ
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBAdvWriteOff,
    WBCampaign,
    WBNormQueryItem,
)
from src.modules.monitoring.models import (
    CLUSTER_MAX_LENGTH,
    PAYMENT_TYPE_MAX_LENGTH,
    normalize_status,
)
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    AdvertisingRepository,
    AdvertisingSearchRepository,
    AdvertisingWriteOffRepository,
    CampaignRepository,
)

logger = get_logger(__name__)


@dataclass
class _SearchZoneAcc:
    """Mutable per-(date, campaign, SKU) accumulator over search clusters."""

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0


@dataclass
class _ClusterAcc:
    """Mutable per-(date, campaign, SKU, cluster) accumulator.

    WB has been observed to repeat a cluster inside one day's ``dailyStats``
    (the same phrase split across entries), so the cluster grain accumulates
    too instead of trusting the payload to be unique per key. ``position_views``
    tracks only the impressions WB reported a position for, so a positionless
    entry cannot dilute the average.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    weighted_position: float = 0.0
    position_views: int = 0

    @property
    def avg_position(self) -> float:
        """Impression-weighted average ad position; 0.0 when WB reported none."""
        if not self.position_views:
            return 0.0
        return self.weighted_position / self.position_views


@dataclass
class _WriteOffAcc:
    """Mutable per-(day, campaign, funding source, currency) money accumulator."""

    amount: Decimal = Decimal(0)
    write_offs: int = 0


class AdvertisingIngestion:
    """Flattens and persists advertising stats, campaign metadata, and search slices."""

    def __init__(
        self,
        *,
        advertising_repo: AdvertisingRepository,
        campaign_repo: CampaignRepository,
        advertising_search_repo: AdvertisingSearchRepository,
        advertising_cluster_repo: AdvertisingClusterRepository,
        advertising_write_off_repo: AdvertisingWriteOffRepository,
    ) -> None:
        """Inject the advertising-family repositories used for persistence."""
        self._advertising = advertising_repo
        self._campaigns = campaign_repo
        self._advertising_search = advertising_search_repo
        self._advertising_clusters = advertising_cluster_repo
        self._advertising_write_offs = advertising_write_off_repo

    async def ingest_advertising(
        self,
        stats: list[WBAdvCampaignStats],
        *,
        window: tuple[date, date] | None = None,
    ) -> int:
        """Flatten the nested advertising trees and persist the records.

        Descends each campaign's ``days -> apps (platform) -> nms (SKU)`` into
        one flat record per ``(date, campaign_id, app_type, nm_id)`` and upserts
        all campaigns in a single batch.

        When ``window`` is supplied, each harvested campaign's rows inside that
        window are deleted first (same transaction). All-zero placeholder rows
        are skipped on insert, so without the sweep a WB correction from
        nonzero down to zero could never overwrite the stale value.

        Args:
            stats: Raw per-campaign full-stats trees from the advertising client.
            window: Optional inclusive ``(date_from, date_to)`` harvest window
                to sweep before inserting.

        Returns:
            The number of advertising rows persisted.
        """
        if window is not None and stats:
            deleted = await self._advertising.delete_window_for_campaigns(
                date_from=window[0],
                date_to=window[1],
                campaign_ids=[c.campaign_id for c in stats],
            )
            logger.info("Swept %d stale advertising rows before refresh.", deleted)

        flattened: list[dict[str, object]] = []
        for campaign in stats:
            for day in campaign.days:
                for app in day.apps:
                    for nm in app.nms:
                        # Skip WB's all-zero placeholder rows (e.g. the
                        # ``appType: 0`` buckets) — they carry no signal and
                        # only add noise to the per-campaign breakdown.
                        if (
                            nm.views == 0
                            and nm.clicks == 0
                            and nm.atbs == 0
                            and nm.sum == 0
                            and nm.orders == 0
                            and nm.sum_price == 0
                        ):
                            continue
                        flattened.append(
                            {
                                "stat_date": day.stat_date,
                                "campaign_id": campaign.campaign_id,
                                "app_type": app.app_type,
                                "nm_id": nm.nm_id,
                                "views": nm.views,
                                "clicks": nm.clicks,
                                "add_to_cart": nm.atbs,
                                "spend": nm.sum,
                                "orders": nm.orders,
                                "order_sum": nm.sum_price,
                            }
                        )
        count = await self._advertising.upsert_many(flattened)
        logger.info("Ingested %d advertising rows across %d campaigns.", count, len(stats))
        return count

    async def ingest_write_offs(
        self,
        write_offs: list[WBAdvWriteOff],
        *,
        window: tuple[date, date],
    ) -> int:
        """Aggregate WB's write-off ledger into daily per-campaign buckets.

        Reduces ``(updTime, advertId, paymentType, currency)`` rows to one row
        per Moscow day, campaign, funding source and currency. Three properties
        of the source dictate that grain, and each of them has already produced
        a wrong figure when ignored:

        * WB's ``updNum`` is **0 on every cashback row**, so it can key nothing.
        * ``currency`` varies inside one window, so it must not be summed across.
        * A campaign is charged many times a day, so the day is the useful grain
          and the individual charge is not.

        ``updTime`` is normalised to the Moscow day the rest of the monitoring
        time series is dated by, rather than trusting whatever offset WB stamped
        the row with.

        Rows in the window are swept for the campaigns present in the payload
        before insert, so a WB restatement that removes a charge cannot leave the
        old one behind. The sweep is campaign-scoped because the feed is served
        per advertising token: a bare window sweep would delete another
        workspace's ledger.

        Args:
            write_offs: Raw ledger rows from the advertising client.
            window: Inclusive ``(date_from, date_to)`` the ledger was asked for.

        Returns:
            The number of bucket rows persisted.
        """
        buckets: dict[tuple[date, int, str, str], _WriteOffAcc] = {}
        for row in write_offs:
            day = row.upd_time.astimezone(MOSCOW_TZ).date()
            # A charge WB stamped outside the asked-for window would survive the
            # sweep below and double-count on the next pass over its own window.
            if not window[0] <= day <= window[1]:
                continue
            key = (day, row.campaign_id, row.payment_type, row.currency)
            acc = buckets.setdefault(key, _WriteOffAcc())
            acc.amount += row.upd_sum
            acc.write_offs += 1

        campaign_ids = sorted({row.campaign_id for row in write_offs})
        if campaign_ids:
            deleted = await self._advertising_write_offs.delete_window_for_campaigns(
                date_from=window[0], date_to=window[1], campaign_ids=campaign_ids
            )
            logger.info("Swept %d stale advertising write-off rows before refresh.", deleted)

        rows: list[dict[str, object]] = [
            {
                "stat_date": day,
                "campaign_id": campaign_id,
                "payment_type": payment_type[:PAYMENT_TYPE_MAX_LENGTH],
                "currency": currency[:8],
                "amount": acc.amount,
                "write_offs": acc.write_offs,
            }
            for (day, campaign_id, payment_type, currency), acc in buckets.items()
        ]
        count = await self._advertising_write_offs.upsert_many(rows)
        logger.info(
            "Ingested %d advertising write-off buckets from %d WB rows.", count, len(write_offs)
        )
        return count

    async def ingest_campaigns(
        self,
        campaigns: list[WBCampaign],
        adverts: list[WBAdvertV2] | None = None,
    ) -> int:
        """Upsert advertising-campaign metadata, enriched with v2 settings.

        ``promotion/count`` supplies the type/status backbone; ``adverts``
        (from ``/api/advert/v2/adverts``) decorates each campaign with its bid
        type, display-zone placements, name, and payment model — the fields the
        monitoring matrix classifies campaigns by. When ``adverts`` is ``None``
        (source failed or not requested) the settings columns are left
        untouched so a degraded harvest never wipes previously synced values.

        Args:
            campaigns: Flattened campaign descriptors from ``list_campaigns``.
            adverts: Optional campaign settings from ``list_adverts``.

        Returns:
            The number of campaign rows persisted.
        """
        adverts_by_id = {a.campaign_id: a for a in adverts or []}
        rows: list[dict[str, object]] = []
        for c in campaigns:
            row: dict[str, object] = {
                "campaign_id": c.campaign_id,
                "type": c.type,
                "status": c.status,
                "status_label": normalize_status(c.status),
            }
            if adverts is not None:
                advert = adverts_by_id.get(c.campaign_id)
                row["bid_type"] = advert.bid_type if advert else None
                row["placement_search"] = advert.settings.placements.search if advert else None
                row["placement_recommendations"] = (
                    advert.settings.placements.recommendations if advert else None
                )
                row["name"] = advert.settings.name if advert else None
                row["payment_type"] = advert.settings.payment_type if advert else None
            rows.append(row)
        count = await self._campaigns.upsert_many(rows, with_settings=adverts is not None)
        logger.info("Ingested %d campaign rows (%d with v2 settings).", count, len(adverts_by_id))
        return count

    async def ingest_search_stats(
        self,
        items: list[WBNormQueryItem],
        *,
        window: tuple[date, date] | None = None,
        requested_campaign_ids: list[int] | None = None,
    ) -> int:
        """Flatten and persist daily SEARCH-zone advertising slices.

        Each normquery item carries one ``dailyStats`` entry per day x search
        cluster; clusters are summed into one record per
        ``(date, campaign_id, nm_id)`` — the grain the analytics layer joins
        against the fullstats facts to split unified campaigns by zone.

        When ``window`` is supplied, the requested campaigns' rows inside it are
        deleted first (same transaction), mirroring the advertising sweep: a
        campaign whose search traffic dropped to zero would otherwise keep its
        stale slice forever.

        Args:
            items: Raw per-(campaign, SKU) search-cluster stats.
            window: Optional inclusive ``(date_from, date_to)`` harvest window
                to sweep before inserting.
            requested_campaign_ids: Every campaign the harvest asked stats for
                (a superset of the campaigns present in ``items``); defaults to
                the campaigns in ``items``.

        Returns:
            The number of search-zone rows persisted.
        """
        if window is not None:
            swept_ids = (
                requested_campaign_ids
                if requested_campaign_ids is not None
                else [item.campaign_id for item in items]
            )
            deleted = await self._advertising_search.delete_window_for_campaigns(
                date_from=window[0], date_to=window[1], campaign_ids=swept_ids
            )
            if deleted:
                logger.info("Swept %d stale search-zone rows before refresh.", deleted)

        accumulated: dict[tuple[date, int, int], _SearchZoneAcc] = {}
        for item in items:
            for daily in item.daily_stats:
                key = (daily.stat_date, item.campaign_id, item.nm_id)
                acc = accumulated.setdefault(key, _SearchZoneAcc())
                stat = daily.stat
                acc.views += stat.views
                acc.clicks += stat.clicks
                acc.add_to_cart += stat.atbs
                acc.spend += stat.spend
                acc.orders += stat.orders

        # All-zero day rows carry no signal — mirror the advertising skip.
        flattened: list[dict[str, object]] = [
            {
                "stat_date": stat_date,
                "campaign_id": campaign_id,
                "nm_id": nm_id,
                "views": acc.views,
                "clicks": acc.clicks,
                "add_to_cart": acc.add_to_cart,
                "spend": acc.spend,
                "orders": acc.orders,
            }
            for (stat_date, campaign_id, nm_id), acc in accumulated.items()
            if acc.views or acc.clicks or acc.add_to_cart or acc.spend or acc.orders
        ]
        count = await self._advertising_search.upsert_many(flattened)
        logger.info("Ingested %d search-zone rows from %d normquery items.", count, len(items))
        return count

    async def ingest_search_clusters(
        self,
        items: list[WBNormQueryItem],
        *,
        window: tuple[date, date] | None = None,
        requested_campaign_ids: list[int] | None = None,
    ) -> int:
        """Persist the SAME normquery payload at its per-CLUSTER grain.

        :meth:`ingest_search_stats` sums the clusters away to answer "how much of
        this campaign-day was the search zone". This keeps the cluster texts,
        which is what «Поиск по кластерам» searches — the only record of which
        search phrases the seller's ads actually appeared for.

        Entries WB returns without a cluster text are dropped rather than
        persisted under a blank key: they are not a phrase anyone can search for,
        and their metrics are already counted by the zone aggregate.

        Args:
            items: Raw per-(campaign, SKU) search-cluster stats.
            window: Optional inclusive ``(date_from, date_to)`` harvest window to
                sweep before inserting. Sweeping matters more here than for the
                aggregate: a campaign that stopped bidding on a cluster emits no
                row for it, so without the sweep the dropped phrase would stay
                in the seller's report forever.
            requested_campaign_ids: Every campaign the harvest asked stats for (a
                superset of those present in ``items``); defaults to the
                campaigns in ``items``.

        Returns:
            The number of per-cluster rows persisted.
        """
        if window is not None:
            swept_ids = (
                requested_campaign_ids
                if requested_campaign_ids is not None
                else [item.campaign_id for item in items]
            )
            deleted = await self._advertising_clusters.delete_window_for_campaigns(
                date_from=window[0], date_to=window[1], campaign_ids=swept_ids
            )
            if deleted:
                logger.info("Swept %d stale search-cluster rows before refresh.", deleted)

        accumulated: dict[tuple[date, int, int, str], _ClusterAcc] = {}
        skipped_unlabelled = 0
        for item in items:
            for daily in item.daily_stats:
                stat = daily.stat
                # Truncated to the column width — WB's clusters are short
                # phrases, so this is a guard, not an expected path.
                cluster = stat.norm_query.strip()[:CLUSTER_MAX_LENGTH]
                if not cluster:
                    skipped_unlabelled += 1
                    continue
                key = (daily.stat_date, item.campaign_id, item.nm_id, cluster)
                acc = accumulated.setdefault(key, _ClusterAcc())
                acc.views += stat.views
                acc.clicks += stat.clicks
                acc.add_to_cart += stat.atbs
                acc.spend += stat.spend
                acc.orders += stat.orders
                if stat.avg_position > 0:
                    acc.weighted_position += stat.avg_position * stat.views
                    acc.position_views += stat.views

        # All-zero rows carry no signal — mirror the advertising/zone skip.
        flattened: list[dict[str, object]] = [
            {
                "stat_date": stat_date,
                "campaign_id": campaign_id,
                "nm_id": nm_id,
                "cluster": cluster,
                "views": acc.views,
                "clicks": acc.clicks,
                "add_to_cart": acc.add_to_cart,
                "spend": acc.spend,
                "orders": acc.orders,
                "avg_position": acc.avg_position,
            }
            for (stat_date, campaign_id, nm_id, cluster), acc in accumulated.items()
            if acc.views or acc.clicks or acc.add_to_cart or acc.spend or acc.orders
        ]
        count = await self._advertising_clusters.upsert_many(flattened)
        logger.info(
            "Ingested %d search-cluster rows from %d normquery items (%d unlabelled skipped).",
            count,
            len(items),
            skipped_unlabelled,
        )
        return count
