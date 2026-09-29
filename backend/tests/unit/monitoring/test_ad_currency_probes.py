"""How the ad-currency backfill groups old campaigns into fullstats calls.

fullstats names a campaign's currency only if the campaign delivered inside the
call's window, and a call takes at most 31 days and 50 campaigns. A plan that
breaks either rule labels nothing and costs the call anyway, on a surface paced
at one request per 20 s.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.monitoring.services.ad_currency import plan_currency_probes


def test_campaigns_that_ran_in_the_same_month_share_one_call() -> None:
    """Three campaigns within 31 days of each other cost a single request."""
    last_days = {1: date(2026, 9, 20), 2: date(2026, 9, 5), 3: date(2026, 8, 25)}

    probes = plan_currency_probes(last_days)

    assert len(probes) == 1
    assert probes[0].campaign_ids == [1, 2, 3]
    assert (probes[0].begin, probes[0].end) == (date(2026, 8, 25), date(2026, 9, 20))


def test_every_campaign_delivered_inside_its_calls_window() -> None:
    """A window never leaves out the last day that proves a campaign answers."""
    start = date(2025, 1, 1)
    last_days = {campaign: start + timedelta(days=campaign * 7) for campaign in range(1, 80)}

    probes = plan_currency_probes(last_days)

    for probe in probes:
        assert (probe.end - probe.begin).days < 31
        for campaign in probe.campaign_ids:
            assert probe.begin <= last_days[campaign] <= probe.end
    assert sorted(c for probe in probes for c in probe.campaign_ids) == sorted(last_days)


def test_a_crowded_month_is_split_at_fifty_campaigns() -> None:
    """120 campaigns on one day need three calls — WB caps the id list at 50."""
    last_days = {campaign: date(2026, 9, 1) for campaign in range(120)}

    probes = plan_currency_probes(last_days)

    assert [len(probe.campaign_ids) for probe in probes] == [50, 50, 20]


def test_nothing_missing_asks_nothing() -> None:
    """A second run, after everything is labelled, makes no request."""
    assert plan_currency_probes({}) == []
