"""The advertising page's campaign-grain facts answer for ONE кабинет.

Three of the four sources behind :func:`load_ad_campaign_facts` carry no tenant
of their own — the campaign dimension, the search slice's campaigns and the
bonus ledger are keyed by WB ids that are global — so what keeps another
seller's campaigns off the page is SQL: the ``product_card`` semijoin, and the
restriction of everything else to the campaigns that spent on our cards. That
is why this lives in the integration tier; a fake would assert nothing about it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.contract import load_ad_campaign_facts, load_ad_currencies
from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    Campaign,
    ProductCard,
)
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

pytestmark = pytest.mark.integration

MINE = 111111111
THEIRS = 222222222
MY_CAMPAIGN = 501
THEIR_CAMPAIGN = 502
DAY = date(2026, 9, 14)


async def _workspace(session: AsyncSession, name: str, nm_id: int) -> Workspace:
    """Persist a workspace in its own organisation, owning one card."""
    org = Organization(name=f"Орг {name}", is_primary=False)
    session.add(org)
    await session.flush()
    workspace = Workspace(organization_id=org.id, name=name)
    session.add(workspace)
    await session.flush()
    session.add(ProductCard(nm_id=nm_id, workspace_id=workspace.id, vendor_code=f"A-{nm_id}"))
    await session.flush()
    return workspace


def _spend(campaign_id: int, nm_id: int, spend: str, app_type: int = 1) -> AdvertisingStatDaily:
    """One fullstats row."""
    return AdvertisingStatDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        app_type=app_type,
        nm_id=nm_id,
        views=10,
        clicks=1,
        add_to_cart=0,
        spend=Decimal(spend),
        orders=0,
    )


def _campaign(campaign_id: int, bid_type: str) -> Campaign:
    """A synced campaign dimension row."""
    return Campaign(
        campaign_id=campaign_id,
        type=9,
        status=9,
        status_label="active",
        bid_type=bid_type,
        payment_type="cpm",
        placement_search=True,
        placement_recommendations=True,
    )


def _bonus(campaign_id: int, amount: str) -> AdvertisingWriteOffDaily:
    """One day of WB-funded write-offs for a campaign."""
    return AdvertisingWriteOffDaily(
        stat_date=DAY,
        campaign_id=campaign_id,
        payment_type="Кэшбэк",
        currency="KGS",
        amount=Decimal(amount),
        write_offs=1,
    )


async def test_another_tenants_campaigns_never_reach_the_page(db_session: AsyncSession) -> None:
    """Spend, search slice, campaign settings and bonus are all ours alone."""
    mine = await _workspace(db_session, "Мой", MINE)
    await _workspace(db_session, "Чужой", THEIRS)
    db_session.add_all(
        [
            _spend(MY_CAMPAIGN, MINE, "100", app_type=1),
            _spend(MY_CAMPAIGN, MINE, "50", app_type=4),
            _spend(THEIR_CAMPAIGN, THEIRS, "9000"),
            AdvertisingSearchStatDaily(
                stat_date=DAY, campaign_id=MY_CAMPAIGN, nm_id=MINE, views=5, spend=Decimal("60")
            ),
            AdvertisingSearchStatDaily(
                stat_date=DAY,
                campaign_id=THEIR_CAMPAIGN,
                nm_id=THEIRS,
                views=5,
                spend=Decimal("700"),
            ),
            _campaign(MY_CAMPAIGN, "manual"),
            _campaign(THEIR_CAMPAIGN, "unified"),
            _bonus(MY_CAMPAIGN, "40"),
            _bonus(THEIR_CAMPAIGN, "4000"),
        ]
    )
    await db_session.flush()

    facts = await load_ad_campaign_facts(
        db_session, workspace_id=mine.id, date_from=DAY, date_to=DAY
    )

    assert [(row.campaign_id, row.nm_id, row.spend) for row in facts.spend] == [
        (MY_CAMPAIGN, MINE, Decimal("150"))
    ]
    assert [(row.campaign_id, row.spend) for row in facts.search] == [(MY_CAMPAIGN, Decimal("60"))]
    assert [(row.campaign_id, row.bid_type) for row in facts.campaigns] == [(MY_CAMPAIGN, "manual")]
    assert [(row.campaign_id, row.amount) for row in facts.bonus] == [
        (MY_CAMPAIGN, Decimal("40.00"))
    ]


async def test_a_shared_campaigns_bonus_is_cut_to_our_share_of_its_spend(
    db_session: AsyncSession,
) -> None:
    """A campaign that also advertised a foreign card hands us only our part of its bonus.

    The ledger names a campaign, not a card, so without the scaling every сом
    WB paid for the other seller's impressions would land on our page.
    """
    mine = await _workspace(db_session, "Мой", MINE)
    await _workspace(db_session, "Чужой", THEIRS)
    db_session.add_all(
        [
            _spend(MY_CAMPAIGN, MINE, "100"),
            _spend(MY_CAMPAIGN, THEIRS, "300"),
            _bonus(MY_CAMPAIGN, "80"),
        ]
    )
    await db_session.flush()

    facts = await load_ad_campaign_facts(
        db_session, workspace_id=mine.id, date_from=DAY, date_to=DAY
    )

    assert [row.amount for row in facts.bonus] == [Decimal("20.00")]


async def test_currencies_and_ledger_coverage_match_the_standalone_loaders(
    db_session: AsyncSession,
) -> None:
    """The facts answer «which currencies» and «is the ledger there» as the old loaders did.

    The page used to ask `load_ad_currencies` and `ad_bonus_coverage` in two
    more passes over the same tables; the facts now carry both. A row from
    before the campaign label existed («») falls back to the ledger's cash
    label, never to its bonus one.
    """
    mine = await _workspace(db_session, "Мой", MINE)
    unlabelled = _spend(MY_CAMPAIGN, MINE, "100")
    unlabelled.currency = ""
    labelled = _spend(THEIR_CAMPAIGN, MINE, "40")
    labelled.currency = "KGS"
    cash = _bonus(MY_CAMPAIGN, "60")
    cash.payment_type = "Баланс"
    cash.currency = "RUB"
    bonus = _bonus(MY_CAMPAIGN, "10")
    bonus.currency = "BYN"
    db_session.add_all([unlabelled, labelled, cash, bonus])
    await db_session.flush()
    window = {"workspace_id": mine.id, "date_from": DAY, "date_to": DAY}

    facts = await load_ad_campaign_facts(db_session, **window)

    assert list(facts.currencies) == await load_ad_currencies(db_session, **window)
    assert list(facts.currencies) == ["KGS", "RUB"]
    assert facts.ledger_known is True
