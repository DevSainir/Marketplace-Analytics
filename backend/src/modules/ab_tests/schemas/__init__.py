"""HTTP schemas of the A/B-tests module.

What crosses the boundary in both directions. Ratios are computed on read and
serialised as ``null`` where their denominator is empty — the SPA renders "—"
for those, the way WB's own result table does, because 0 % and "not measured
yet" are different answers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.exceptions import UserInputError
from src.core.exceptions import ValidationError as DomainValidationError
from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.services.triggers import resolve as resolve_trigger


class AbTestCreate(BaseModel):
    """Request body for creating a test.

    ``vendor_code`` is deliberately absent: it is read off the catalogue card the
    ``nm_id`` resolves to. Taking it from the client would let the two disagree,
    and the vendor code is what the list is searched by.

    A single-bound mode refuses the other bound rather than quietly ignoring
    it: sending ``slot_minutes`` with ``trigger_mode="impressions"`` is a 422,
    not a silently dropped field. ``trigger_mode="either"`` is the mode that
    takes both, because it is the mode that reads both — whichever is reached
    first ends the turn.
    """

    nm_id: int = Field(gt=0, description="WB ID whose main photo is rotated")
    name: str = Field(min_length=1, max_length=255, description="Test name")
    trigger_mode: TriggerMode = Field(
        default=TriggerMode.IMPRESSIONS,
        description="What moves the rotation: impressions, time, or whichever comes first",
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Impressions per variant. Modes `impressions` and `either`",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Minutes per variant. Modes `time` and `either`",
    )

    @model_validator(mode="after")
    def _one_trigger_only(self) -> AbTestCreate:
        """Apply the module's trigger rule, then fill in what was not supplied.

        The rule itself lives in :mod:`.services.triggers` because the settings
        PATCH has to apply the identical one against a stored test; a second
        copy here would drift the moment either path changed.
        """
        try:
            resolved = resolve_trigger(
                mode=self.trigger_mode,
                impression_budget=self.impression_budget,
                slot_minutes=self.slot_minutes,
            )
        except DomainValidationError as exc:
            # Pydantic turns a ValueError into a 422; an AppError raised here
            # would escape as a 500 instead.
            raise UserInputError(str(exc)) from exc

        object.__setattr__(self, "impression_budget", resolved.impression_budget)
        object.__setattr__(self, "slot_minutes", resolved.slot_minutes)
        return self


class SkuOption(BaseModel):
    """One catalogue card a test may be created against.

    The two ranking fields are what the picker is ORDERED by, and they are
    returned rather than kept server-side so the list can say why a card is near
    the top — an order with no visible reason reads as an arbitrary one.
    """

    nm_id: int = Field(description="WB ID")
    vendor_code: str = Field(description="Vendor code")
    title: str = Field(description="Product card title")
    orders_7d: int = Field(default=0, description="Orders over the last week")
    has_ads: bool = Field(default=False, description="Advertised over the last week")


class AbTestSettingsUpdate(BaseModel):
    """Request body for changing a test's name or its rotation trigger.

    Every field is optional: sending only ``impression_budget`` keeps the mode
    the test already has. The bound rule is checked against the *resolved*
    mode — the one in the body if it names one, otherwise the stored one — so
    "set slot_minutes on a test that is still counting impressions" is refused
    even though the body never mentions a mode, while a test in mode
    «either» takes either field on its own. That check needs the stored test, so it
    happens in the service rather than here.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger_mode: TriggerMode | None = Field(
        default=None, description="Switch the mode: impressions, time, or both at once"
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Impressions per variant. Modes `impressions` and `either`",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Minutes per variant. Modes `time` and `either`",
    )


class CampaignTotals(BaseModel):
    """What one advertising campaign brought the test, over all of its photos.

    The branches under each figure of "Test summary". They sum to the figure
    above them, because both are summed from the same interval rows — the split
    happens where the counters arrive, not where they are drawn.
    """

    campaign_id: int = Field(description="WB campaign id; 0 — data from before the split")
    name: str = Field(description="Campaign name in the WB seller portal")
    kind: str = Field(
        description="Campaign kind: uni | manual_search | manual_shelves | cpc | unknown"
    )

    views: int = Field(description="Impressions this campaign brought")
    clicks: int = Field(description="Card clicks from this campaign")
    atbs: int = Field(description="Adds to cart from this campaign")
    orders: int = Field(description="Orders from this campaign")
    spend: Decimal = Field(description="This campaign's spend over the counted intervals")

    click_through: Decimal | None = Field(description="This campaign's CTR over the whole test, %")
    add_to_cart: Decimal | None = Field(description="Adds to cart / clicks for this campaign, %")
    order_rate: Decimal | None = Field(description="Orders / adds to cart for this campaign, %")


class VariantCampaignMetrics(BaseModel):
    """One photo's figures inside ONE campaign.

    Everything is recomputed within the campaign, the gap to the leader
    included: a photo can lead "Unified" and trail "CPC", and that is precisely
    what the whole-test row cannot show.
    """

    campaign_id: int = Field(description="The campaign these figures were counted in")

    views: int
    clicks: int
    atbs: int
    orders: int
    spend: Decimal

    click_through: Decimal | None = Field(description="Click-through rate, %")
    add_to_cart: Decimal | None = Field(description="Add-to-cart rate, %")
    order_rate: Decimal | None = Field(description="Order rate, %")

    ctr_gap: Decimal | None = Field(description="CTR gap to the best IN THIS CAMPAIGN, pp")
    ctr_result: Decimal | None = Field(description="The same gap, in percent")

    rounds_played: int = Field(
        default=0,
        description=(
            "How many rounds this campaign brought this photo impressions in. "
            "Not the test's rounds: a campaign switched off in round four played four."
        ),
    )


class ExposureCampaignCounts(BaseModel):
    """What one turn earned from one campaign.

    Absent for a campaign that earned nothing in the turn — the timeline reads
    "this ad campaign ran in this lap" off the presence of an entry.
    """

    campaign_id: int
    views: int = 0
    clicks: int = 0
    click_through: Decimal | None = Field(default=None, description="CTR for this install, %")


class VariantMetrics(BaseModel):
    """One photo's row in the result table.

    The field order mirrors the columns the UI renders, which is the order WB's
    own A/B result screen uses: the three chained ratios first, then the raw
    counts they are derived from.
    """

    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    position: int
    image_url: str = Field(description="Where the SPA fetches the image itself")
    is_active: bool = Field(description="This photo is on the card right now")
    is_original: bool = Field(
        default=False,
        description="The main photo — the baseline the others are compared with; position 0",
    )
    is_excluded: bool = Field(
        default=False,
        description="Removed from the rotation: sits out the next rounds, metrics kept",
    )

    rounds_played: int = Field(default=0, description="How many rounds the photo took part in")
    ctr_gap: Decimal | None = Field(
        default=None, description="CTR gap to the best, in percentage points"
    )
    ctr_result: Decimal | None = Field(
        default=None, description="The same gap relative to the best, in percent"
    )

    click_through: Decimal | None = Field(description="Click-through rate, %")
    add_to_cart: Decimal | None = Field(description="Add-to-cart rate, %")
    order_rate: Decimal | None = Field(description="Order rate, %")

    views: int = Field(description="Card impressions in search results")
    clicks: int = Field(description="Card clicks")
    atbs: int = Field(description="Adds to cart")
    orders: int = Field(description="Orders placed")
    spend: Decimal = Field(description="Advertising spend over this variant's days")

    days_measured: int = Field(description="Full days credited to this photo")

    campaigns: list[VariantCampaignMetrics] = Field(
        default_factory=list,
        description=(
            "The same metrics for each advertising campaign separately, in the order "
            "Unified, Manual search, Manual shelves, CPC. Empty for a test with no "
            "measurements."
        ),
    )


class AbTestSummary(BaseModel):
    """Everything one test has counted, over all of its photos and turns.

    Summed from the same interval rows the result table divides, so the figures
    here are the column sums of that table and can be checked against it by
    adding them up. See :mod:`..services.summary` for why that is the point.

    The two durations answer different questions and are both reported. This
    one, ``measured_minutes``, is the exposure the ratios are divided over; the
    wall clock is derived by the client from ``started_at``/``finished_at``,
    because for a live test it ends at "now" and any stored value of it is
    stale the moment it is serialised.
    """

    views: int = Field(description="Card impressions in advertising over the whole test")
    clicks: int = Field(description="Card clicks over the whole test")
    atbs: int = Field(description="Adds to cart over the whole test")
    orders: int = Field(description="Orders placed over the whole test")
    spend: Decimal = Field(description="Advertising spend on this SKU over the measured intervals")

    click_through: Decimal | None = Field(description="Clicks / impressions over the whole test, %")
    add_to_cart: Decimal | None = Field(description="Adds to cart / clicks over the whole test, %")
    order_rate: Decimal | None = Field(description="Orders / adds to cart over the whole test, %")

    measured_minutes: int = Field(
        description=(
            "Total length of the counted intervals — the time these figures were "
            "collected over. Less than the time since the start by every stretch the "
            "test stood without advertising or paused."
        )
    )
    windows: int = Field(description="How many polling intervals were counted")
    first_window_at: datetime | None = Field(
        default=None, description="Start of the earliest counted interval"
    )
    last_window_at: datetime | None = Field(
        default=None, description="End of the latest counted interval — data up to this hour"
    )

    rounds_completed: int = Field(default=0, description="Rounds the rotation has completed")
    variants_measured: int = Field(default=0, description="Photos that have gathered impressions")
    variants_total: int = Field(default=0, description="Photos in the test")


class AbTestRead(BaseModel):
    """A test as the list and the detail page show it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nm_id: int
    vendor_code: str
    name: str
    status: str
    trigger_mode: str
    impression_budget: int
    slot_minutes: int
    active_variant_id: uuid.UUID | None
    variant_count: int
    started_at: datetime | None
    finished_at: datetime | None
    stopped_at: datetime | None = Field(
        default=None,
        description=("When the rotation last stopped — a pause or a finish. Cleared on resume."),
    )
    photo_conflict_at: datetime | None = Field(
        default=None,
        description=(
            "When the rotation found a main photo on the card that it had not "
            "installed: the card was changed by hand. The test is stopped and will not "
            "resume by itself — traffic on a foreign photo belongs to no variant. "
            "null if that never happened."
        ),
    )
    paused_by_ads: bool = Field(
        default=False,
        description=(
            "The rotation paused the test: no campaign with a budget is serving the "
            "SKU. It resumes by itself once advertising runs. false — paused by hand "
            "or not paused."
        ),
    )
    created_at: datetime

    leader_variant_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The variant with the best CTR among those with at least one full day. "
            "None while there is nothing to compare."
        ),
    )


class AbTestDetail(AbTestRead):
    """A test plus the per-photo result table and the log of its turns."""

    variants: list[VariantMetrics] = Field(default_factory=list)
    history: list[ExposureRow] = Field(
        default_factory=list, description="Every photo install, newest first"
    )
    rounds_completed: int = Field(default=0, description="Rounds the rotation has completed")

    active_since: datetime | None = Field(
        default=None,
        description=(
            "When the current photo went up on the card. Where the slot is counted "
            "from in `time` mode; null while nothing is installed."
        ),
    )

    summary: AbTestSummary = Field(description="Test summary — the sum of the table rows")

    campaigns: list[CampaignTotals] = Field(
        default_factory=list,
        description=(
            "Advertising campaigns that actually brought the test traffic, in the order "
            "Unified, Manual search, Manual shelves, CPC. One campaign — the page "
            "looks as before; two or more — the split and the campaign picker appear. "
            "A campaign switched off mid-test stays here: its impressions did not "
            "go anywhere."
        ),
    )


class VariantExclusionUpdate(BaseModel):
    """Request body for taking a photo out of the rotation, or putting it back."""

    excluded: bool = Field(description="true — remove from the rotation, false — bring back")


class ExposureRow(BaseModel):
    """One turn in "Rotation history": a photo installed, and what it earned."""

    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    position: int
    is_original: bool
    image_url: str
    round_number: int = Field(description="The round this install belongs to")
    activated_at: datetime = Field(description="When WB accepted the upload")
    deactivated_at: datetime | None = Field(default=None, description="When the photo came down")
    minutes: int | None = Field(default=None, description="Minutes the photo stayed up")

    views: int = 0
    clicks: int = 0
    click_through: Decimal | None = Field(default=None, description="CTR for this install, %")

    campaigns: list[ExposureCampaignCounts] = Field(
        default_factory=list,
        description="The same install split by campaign; campaigns with no traffic are absent",
    )


class AbTestStatusUpdate(BaseModel):
    """Request body for starting, pausing or cancelling a test."""

    status: str = Field(description="running | paused | cancelled")


class AbTestFinish(BaseModel):
    """Request body for finishing a test: which photo the card keeps."""

    keep_variant_id: uuid.UUID = Field(description="The photo that stays on the card")
