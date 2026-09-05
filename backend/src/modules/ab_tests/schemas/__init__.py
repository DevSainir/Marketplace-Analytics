"""HTTP schemas of the A/B-tests module.

What crosses the boundary in both directions. Ratios are computed on read and
serialised as ``null`` where their denominator is empty — the SPA renders «—»
for those, the way WB's own result table does, because 0 % and "not measured
yet" are different answers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.exceptions import ValidationError as DomainValidationError
from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.services.triggers import resolve as resolve_trigger


class AbTestCreate(BaseModel):
    """Request body for creating a test.

    ``vendor_code`` is deliberately absent: it is read off the catalogue card the
    ``nm_id`` resolves to. Taking it from the client would let the two disagree,
    and the seller article is what the list is searched by.

    The two triggers are mutually exclusive, and the model enforces it rather
    than quietly ignoring the unused one: sending ``slot_minutes`` with
    ``trigger_mode="impressions"`` is a 422, not a silently dropped field. A
    test that rotated on "either, whichever first" would measure its variants
    over different exposures, which is the one thing a budget exists to prevent.
    """

    nm_id: int = Field(gt=0, description="Артикул WB, чьё главное фото ротируется")
    name: str = Field(min_length=1, max_length=255, description="Название теста")
    trigger_mode: TriggerMode = Field(
        default=TriggerMode.IMPRESSIONS,
        description="Что двигает ротацию: показы или время",
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Показов на вариант. Только для режима «по показам»",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Минут на вариант. Только для режима «по времени»",
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
            raise ValueError(str(exc)) from exc

        object.__setattr__(self, "impression_budget", resolved.impression_budget)
        object.__setattr__(self, "slot_minutes", resolved.slot_minutes)
        return self


class SkuOption(BaseModel):
    """One catalogue card a test may be created against.

    The two ranking fields are what the picker is ORDERED by, and they are
    returned rather than kept server-side so the list can say why a card is near
    the top — an order with no visible reason reads as an arbitrary one.
    """

    nm_id: int = Field(description="Артикул WB")
    vendor_code: str = Field(description="Артикул продавца")
    title: str = Field(description="Название карточки")
    orders_7d: int = Field(default=0, description="Заказов за последнюю неделю")
    has_ads: bool = Field(default=False, description="Есть реклама за последнюю неделю")


class AbTestSettingsUpdate(BaseModel):
    """Request body for changing a test's name or its rotation trigger.

    Every field is optional: sending only ``impression_budget`` keeps the mode
    the test already has. The exclusivity is checked against the *resolved*
    mode — the one in the body if it names one, otherwise the stored one — so
    "set slot_minutes on a test that is still counting impressions" is refused
    even though the body never mentions a mode. That check needs the stored
    test, so it happens in the service rather than here.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger_mode: TriggerMode | None = Field(
        default=None, description="Сменить режим: показы или время"
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Показов на вариант. Только для режима «по показам»",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Минут на вариант. Только для режима «по времени»",
    )


class VariantMetrics(BaseModel):
    """One photo's row in the result table.

    The field order mirrors the columns the UI renders, which is the order WB's
    own A/B result screen uses: the three chained ratios first, then the raw
    counts they are derived from.
    """

    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    position: int
    image_url: str = Field(description="Где SPA заберёт само изображение")
    is_active: bool = Field(description="Это фото сейчас стоит на карточке")

    click_through: Decimal | None = Field(description="Доля переходов в карточку, %")
    add_to_cart: Decimal | None = Field(description="Доля добавлений в корзину, %")
    order_rate: Decimal | None = Field(description="Доля оформлений заказов, %")

    views: int = Field(description="Показы карточки в выдаче")
    clicks: int = Field(description="Переходы в карточку")
    atbs: int = Field(description="Добавления в корзину")
    orders: int = Field(description="Оформления заказов")
    spend: Decimal = Field(description="Расход на рекламу за дни этого варианта")

    days_measured: int = Field(description="Сколько полных дней зачтено этому фото")


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
    created_at: datetime

    leader_variant_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Вариант с лучшим CTR среди набравших хотя бы один полный день. "
            "None, пока сравнивать нечего."
        ),
    )


class AbTestDetail(AbTestRead):
    """A test plus the per-photo result table."""

    variants: list[VariantMetrics] = Field(default_factory=list)


class AbTestStatusUpdate(BaseModel):
    """Request body for starting, pausing or cancelling a test."""

    status: str = Field(description="running | paused | cancelled")
