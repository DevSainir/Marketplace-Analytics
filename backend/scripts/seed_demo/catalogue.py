"""The demo shop's catalogue: six invented articles and the campaigns that sell them.

Everything here is fiction, and is meant to read as such: the brand is «DEMO»,
the articles are ordinary clothing, and every WildBerries identifier sits in a
range starting at nine billion. WB has issued nothing there, so an id copied out
of the demo — or a «open on WB» link built from one — leads nowhere rather than
to some real seller's card.

The figures are tuned to be plausible for a small apparel seller (a few hundred
card opens a day per article, buyout rates in the 40-70 % band WB clothing
actually sees), not to resemble any particular one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: The one currency of the demo. WB settles Russian sellers in roubles, and a
#: single currency end to end means no exchange rate is ever consulted.
CURRENCY = "RUB"

BRAND = "DEMO"

#: The id ranges. Far above anything WB has issued (see the module docstring),
#: and far apart from each other so a stray id names its kind at a glance.
NM_ID_BASE = 9_000_000_100
CAMPAIGN_ID_BASE = 9_000_009_000
REPORT_ID_BASE = 9_000_100_000
RRD_ID_BASE = 9_000_000_000_000

#: Where the stock lives, with each warehouse's share of it and the region WB
#: files it under.
WAREHOUSES: tuple[tuple[str, str, float], ...] = (
    ("Koledino", "Central", 0.38),
    ("Elektrostal", "Central", 0.24),
    ("Kazan", "Volga", 0.22),
    ("Krasnodar", "South", 0.16),
)


@dataclass(frozen=True)
class DemoSku:
    """One article of the demo shop and the knobs of its simulated demand.

    Attributes:
        nm_id: The WB article id.
        vendor_code: The seller's own article code.
        title: The card title, as a buyer would see it.
        subject: WB's category.
        sizes: Size labels, smallest first.
        list_price: The «before discount» price on the card.
        seller_price: What the seller asks after their own discount.
        cost: The cost of one unit.
        opens: Organic card opens on an ordinary day.
        cart_rate: Share of opens that end in a cart.
        order_rate: Share of carts that end in an order.
        buyout_rate: Share of orders the buyer keeps.
        delivery: What WB charges to carry one unit to a pick-up point.
        stock: Units on WB warehouses right after a supply arrives.
    """

    nm_id: int
    vendor_code: str
    title: str
    subject: str
    sizes: tuple[str, ...]
    list_price: Decimal
    seller_price: Decimal
    cost: Decimal
    opens: int
    cart_rate: float
    order_rate: float
    buyout_rate: float
    delivery: Decimal
    stock: int


SKUS: tuple[DemoSku, ...] = (
    DemoSku(
        nm_id=NM_ID_BASE + 1,
        vendor_code="M-TRX01-BLK",
        title="Men's classic straight trousers, black",
        subject="Trousers",
        sizes=("46", "48", "50", "52", "54"),
        list_price=Decimal("4990"),
        seller_price=Decimal("2490"),
        cost=Decimal("820"),
        opens=760,
        cart_rate=0.085,
        order_rate=0.34,
        buyout_rate=0.56,
        delivery=Decimal("84"),
        stock=620,
    ),
    DemoSku(
        nm_id=NM_ID_BASE + 2,
        vendor_code="M-TRX01-GRY",
        title="Men's classic straight trousers, grey",
        subject="Trousers",
        sizes=("46", "48", "50", "52", "54"),
        list_price=Decimal("4990"),
        seller_price=Decimal("2490"),
        cost=Decimal("820"),
        opens=430,
        cart_rate=0.078,
        order_rate=0.32,
        buyout_rate=0.54,
        delivery=Decimal("84"),
        stock=380,
    ),
    DemoSku(
        nm_id=NM_ID_BASE + 3,
        vendor_code="M-SUI02-NVY",
        title="Men's classic suit, navy",
        subject="Suits",
        sizes=("48", "50", "52", "54"),
        list_price=Decimal("12990"),
        seller_price=Decimal("6990"),
        cost=Decimal("2650"),
        opens=260,
        cart_rate=0.058,
        order_rate=0.29,
        buyout_rate=0.43,
        delivery=Decimal("126"),
        stock=140,
    ),
    DemoSku(
        nm_id=NM_ID_BASE + 4,
        vendor_code="M-HDY03-GRN",
        title="Men's oversized hoodie, olive",
        subject="Hoodies",
        sizes=("S", "M", "L", "XL"),
        list_price=Decimal("3990"),
        seller_price=Decimal("2290"),
        cost=Decimal("760"),
        opens=880,
        cart_rate=0.092,
        order_rate=0.31,
        buyout_rate=0.62,
        delivery=Decimal("92"),
        stock=540,
    ),
    DemoSku(
        nm_id=NM_ID_BASE + 5,
        vendor_code="W-JGR04-BEI",
        title="Women's knit joggers, beige",
        subject="Sweatpants",
        sizes=("XS", "S", "M", "L"),
        list_price=Decimal("3290"),
        seller_price=Decimal("1790"),
        cost=Decimal("540"),
        opens=640,
        cart_rate=0.088,
        order_rate=0.33,
        buyout_rate=0.58,
        delivery=Decimal("78"),
        stock=460,
    ),
    DemoSku(
        nm_id=NM_ID_BASE + 6,
        vendor_code="W-TSH05-WHT",
        title="Women's basic cotton T-shirt, white",
        subject="T-shirts",
        sizes=("XS", "S", "M", "L"),
        list_price=Decimal("1590"),
        seller_price=Decimal("890"),
        cost=Decimal("230"),
        opens=1150,
        cart_rate=0.104,
        order_rate=0.36,
        buyout_rate=0.71,
        delivery=Decimal("66"),
        stock=900,
    ),
)

SKU_BY_NM: dict[int, DemoSku] = {sku.nm_id: sku for sku in SKUS}


@dataclass(frozen=True)
class DemoCampaign:
    """One advertising campaign and how it is set up.

    Attributes:
        campaign_id: The WB campaign id.
        name: What the seller called it.
        bid_type: ``unified`` or ``manual`` (WB's spelling).
        payment_type: ``cpm`` or ``cpc``.
        search / shelves: The placements it buys.
        nm_id: The article it advertises.
        companion: An article that picks up the odd order from its traffic.
        views: Impressions on an ordinary day.
        rate: Price per thousand impressions (CPM) or per click (CPC).
        ctr: Share of impressions that become a click.
        search_share: Share of the impressions bought in search.
        first_day_ago: How many days before today the campaign started.
    """

    campaign_id: int
    name: str
    bid_type: str
    payment_type: str
    search: bool
    shelves: bool
    nm_id: int
    companion: int | None
    views: int
    rate: Decimal
    ctr: float
    search_share: float
    first_day_ago: int


CAMPAIGNS: tuple[DemoCampaign, ...] = (
    DemoCampaign(
        campaign_id=CAMPAIGN_ID_BASE + 1,
        name="Classic trousers — unified bid",
        bid_type="unified",
        payment_type="cpm",
        search=True,
        shelves=True,
        nm_id=NM_ID_BASE + 1,
        companion=NM_ID_BASE + 2,
        views=5200,
        rate=Decimal("210"),
        ctr=0.034,
        search_share=0.62,
        first_day_ago=400,
    ),
    DemoCampaign(
        campaign_id=CAMPAIGN_ID_BASE + 2,
        name="Classic trousers — search",
        bid_type="manual",
        payment_type="cpm",
        search=True,
        shelves=False,
        nm_id=NM_ID_BASE + 1,
        companion=None,
        views=2600,
        rate=Decimal("260"),
        ctr=0.041,
        search_share=0.86,
        first_day_ago=400,
    ),
    DemoCampaign(
        campaign_id=CAMPAIGN_ID_BASE + 3,
        name="Hoodie — shelves",
        bid_type="manual",
        payment_type="cpm",
        search=False,
        shelves=True,
        nm_id=NM_ID_BASE + 4,
        companion=None,
        views=6100,
        rate=Decimal("150"),
        ctr=0.027,
        search_share=0.0,
        first_day_ago=400,
    ),
    DemoCampaign(
        campaign_id=CAMPAIGN_ID_BASE + 4,
        name="T-shirt — pay per click",
        bid_type="manual",
        payment_type="cpc",
        search=True,
        shelves=True,
        nm_id=NM_ID_BASE + 6,
        companion=None,
        views=7400,
        rate=Decimal("7.5"),
        ctr=0.031,
        search_share=0.7,
        first_day_ago=400,
    ),
    DemoCampaign(
        campaign_id=CAMPAIGN_ID_BASE + 5,
        name="Joggers — unified bid",
        bid_type="unified",
        payment_type="cpm",
        search=True,
        shelves=True,
        nm_id=NM_ID_BASE + 5,
        companion=None,
        views=3900,
        rate=Decimal("190"),
        ctr=0.032,
        search_share=0.55,
        first_day_ago=40,
    ),
)


def chrt_id(sku: DemoSku, size_index: int) -> int:
    """The WB size id of one size of an article — derived, so never stored twice."""
    return sku.nm_id * 10 + size_index


def barcode(sku: DemoSku, size_index: int) -> str:
    """A barcode for one size, in the 2-prefix range EAN reserves for in-store use."""
    return f"2{sku.nm_id % 1_000_000_000:09d}{size_index:03d}"


def size_weight(sku: DemoSku, size_index: int) -> float:
    """Share of an article's units in one size: the middle sizes sell most."""
    middle = (len(sku.sizes) - 1) / 2
    raw = [1.0 / (1.0 + abs(index - middle)) for index in range(len(sku.sizes))]
    return raw[size_index] / sum(raw)
