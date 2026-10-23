"""Invariants of the capture catalogue itself.

These are cheap and they all guard the same failure: a source added in a hurry
that looks registered, runs, and silently stores nothing.
"""

from __future__ import annotations

from src.core.config import settings
from src.modules.guide.models import GuideRecord
from src.modules.guide.sources import GUIDE_SOURCES, GuideCadence, sources_for
from src.modules.workspaces.schemas import WorkspaceTokenBundle


def test_every_source_key_is_unique() -> None:
    """Two sources sharing a key would overwrite each other's rows.

    The key is part of ``guide_record``'s primary key, so a collision is silent
    data loss rather than an error.
    """
    keys = [source.key for source in GUIDE_SOURCES]

    assert len(keys) == len(set(keys))


def test_every_source_key_fits_the_column_it_is_stored_in() -> None:
    """A key longer than the column truncates, and then two keys can collide."""
    limit = GuideRecord.__table__.c.source.type.length

    assert all(len(source.key) <= limit for source in GUIDE_SOURCES)


def test_every_source_names_a_host_that_settings_actually_has() -> None:
    """A typo in ``base_url`` would only surface at 02:20, when the scheduled run fires."""
    for source in GUIDE_SOURCES:
        assert hasattr(settings, source.base_url), source.key
        assert source.host(settings).startswith("https://"), source.key


def test_every_source_names_tokens_the_bundle_actually_carries() -> None:
    """A token field the bundle does not have resolves to "" and skips forever.

    ``token_for`` uses ``getattr(..., "")``, so a misspelt field is not an
    error — it is a source that records "no token" every run and nobody
    notices.
    """
    bundle_fields = set(WorkspaceTokenBundle.model_fields)

    for source in GUIDE_SOURCES:
        assert set(source.tokens) <= bundle_fields, source.key


def test_every_cadence_has_at_least_one_source() -> None:
    """A scheduled task with nothing to do is a schedule entry to delete."""
    for cadence in GuideCadence:
        assert sources_for(cadence), cadence.value


def test_the_short_window_feeds_are_the_daily_ones() -> None:
    """The cadence rule, pinned: daily is for feeds a missed day loses.

    Measured 2026-09-12 — claims keep fourteen days, the orders feed a hundred
    and eighty-eight with a paged cursor. Moving either to monthly would mean a
    single failed run costing data that cannot be re-fetched, so this fails if
    somebody rebalances the schedule without saying why.
    """
    daily = {source.key for source in sources_for(GuideCadence.DAILY)}

    assert daily == {"claims", "orders"}


def test_there_is_no_cadence_without_a_feed_to_justify_it() -> None:
    """Two cadences, because only two are earned.

    A weekly one existed for FBS supplies until that feed was dropped as
    unjoinable; keeping an empty cadence warm would mean a scheduled task, a
    lock contender and a beat entry doing nothing every Sunday.
    """
    assert {cadence.value for cadence in GuideCadence} == {"daily", "monthly"}


def test_every_source_says_what_it_is_for_and_how_deep_wb_goes() -> None:
    """The two sentences that make a captured feed worth its rows.

    A capture buffer with no reason recorded per feed becomes a table nobody
    dares delete and nobody can justify keeping.
    """
    for source in GUIDE_SOURCES:
        assert len(source.why) > 40, source.key
        assert len(source.retention) > 20, source.key
