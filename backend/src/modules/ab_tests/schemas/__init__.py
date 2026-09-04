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

from src.modules.ab_tests.models import (
    DEFAULT_IMPRESSION_BUDGET,
    DEFAULT_SLOT_MINUTES,
    TriggerMode,
)


class AbTestCreate(BaseModel):
    """Request body for creating a test.

    The two triggers are mutually exclusive, and the model enforces it rather
    than quietly ignoring the unused one: sending ``slot_minutes`` with
    ``trigger_mode="impressions"`` is a 422, not a silently dropped field. A
    test that rotated on "either, whichever first" would measure its variants
    over different exposures, which is the one thing a budget exists to prevent.
    """

    nm_id: int = Field(gt=0, description="Артикул WB, чьё главное фото ротируется")
    name: str = Field(min_length=1, max_length=255, description="Название теста")
    vendor_code: str = Field(default="", max_length=255, description="Артикул продавца")
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
        """Refuse the setting that belongs to the other mode, then fill defaults."""
        if self.trigger_mode is TriggerMode.IMPRESSIONS:
            if self.slot_minutes is not None:
                raise ValueError(
                    "В режиме «по показам» время на вариант не задаётся — уберите slot_minutes."
                )
            object.__setattr__(
                self, "impression_budget", self.impression_budget or DEFAULT_IMPRESSION_BUDGET
            )
            object.__setattr__(self, "slot_minutes", DEFAULT_SLOT_MINUTES)
        else:
            if self.impression_budget is not None:
                raise ValueError(
                    "В режиме «по времени» бюджет показов не задаётся — уберите impression_budget."
                )
            object.__setattr__(self, "slot_minutes", self.slot_minutes or DEFAULT_SLOT_MINUTES)
            object.__setattr__(self, "impression_budget", DEFAULT_IMPRESSION_BUDGET)
        return self


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
