"""A campaign's closing day must survive the campaign being completed.

WB reports a campaign's status as of NOW, not as of the harvest window. The
seller completes a campaign, WB moves it out of active/paused, and a harvest
that scopes fullstats by status alone stops asking about it — including for the
day it was still delivering on. That day is then never collectable again.

Observed on prod 2026-08-20: the «Демо» rotation finished four campaigns
part-way through the day, and 1 808 RUB (953770957) + 1 360 RUB (995716075) of
that day's spend was dropped while WB was still serving it.
"""

from __future__ import annotations

from src.integrations.wildberries.schemas import WBAdvertNmSetting, WBAdvertV2, WBCampaign
from src.modules.monitoring.tasks.planning import _advertising_harvest_ids

ACTIVE, PAUSED, COMPLETED = 9, 11, 7
NM_ID = 953770957


def _campaign(campaign_id: int, status: int) -> WBCampaign:
    """A promotion/count descriptor with the given status."""
    return WBCampaign(campaign_id=campaign_id, type=9, status=status)


def _advert(campaign_id: int, *nm_ids: int) -> WBAdvertV2:
    """An adverts-v2 descriptor advertising the given SKUs."""
    return WBAdvertV2.model_validate(
        {"id": campaign_id, "nm_settings": [WBAdvertNmSetting(nm_id=nm) for nm in nm_ids]}
    )


def test_a_completed_campaign_with_rows_in_the_window_is_still_pulled() -> None:
    """A campaign WB now calls completed is re-asked if it delivered this window.

    This is the whole point of the recent set: the harvest that follows a
    campaign's completion is the LAST one that could collect its final day, and
    by then WB no longer lists it as active.
    """
    campaigns = [_campaign(90838808, COMPLETED), _campaign(97455941, ACTIVE)]
    adverts = [_advert(90838808, NM_ID), _advert(97455941, NM_ID)]

    harvest_ids = _advertising_harvest_ids(campaigns, adverts, [NM_ID], [90838808])

    assert set(harvest_ids) == {90838808, 97455941}


def test_a_completed_campaign_with_no_rows_in_the_window_stays_out() -> None:
    """Status 7 alone still excludes a campaign — the window is what admits it.

    Otherwise every campaign the account ever ran would join each nightly pull,
    on the most aggressively rate-limited surface WB has.
    """
    campaigns = [_campaign(81942244, COMPLETED), _campaign(97455941, ACTIVE)]
    adverts = [_advert(81942244, NM_ID), _advert(97455941, NM_ID)]

    harvest_ids = _advertising_harvest_ids(campaigns, adverts, [NM_ID], [])

    assert harvest_ids == [97455941]


def test_a_recent_campaign_is_listed_once_when_it_is_also_active() -> None:
    """The two sets are a union, not a concatenation.

    A duplicated id would be sent to WB twice in the same fullstats request and
    ingested twice into the same window sweep.
    """
    campaigns = [_campaign(97455941, ACTIVE), _campaign(97455943, PAUSED)]
    adverts = [_advert(97455941, NM_ID), _advert(97455943, NM_ID)]

    harvest_ids = _advertising_harvest_ids(campaigns, adverts, [NM_ID], [97455941, 97455943])

    assert sorted(harvest_ids) == [97455941, 97455943]
    assert len(harvest_ids) == len(set(harvest_ids))


def test_a_recent_campaign_bypasses_the_nm_settings_scope() -> None:
    """Recent ids are already SKU-scoped by the query that produced them.

    A completed campaign can drop its ``nm_settings``, so filtering the recent
    set through adverts-v2 again would discard exactly the campaigns this
    exists to keep.
    """
    campaigns = [_campaign(90838808, COMPLETED)]
    adverts = [_advert(90838808)]

    harvest_ids = _advertising_harvest_ids(campaigns, adverts, [NM_ID], [90838808])

    assert harvest_ids == [90838808]


def test_a_foreign_active_campaign_is_still_excluded() -> None:
    """Scoping a targeted refresh to the SKU's own campaigns is unchanged.

    The recent set widens what a harvest asks for; it must not widen it to the
    rest of the account's campaigns, which is what keeps «Обновить» fast.
    """
    campaigns = [_campaign(97455941, ACTIVE), _campaign(97136532, ACTIVE)]
    adverts = [_advert(97455941, NM_ID), _advert(97136532, 1944299862)]

    harvest_ids = _advertising_harvest_ids(campaigns, adverts, [NM_ID], [])

    assert harvest_ids == [97455941]
