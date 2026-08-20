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

from pydantic import BaseModel, ConfigDict, Field

from src.modules.ab_tests.models import DEFAULT_IMPRESSION_BUDGET


class AbTestCreate(BaseModel):
    """Request body for creating a test."""

    nm_id: int = Field(gt=0, description="Артикул WB, чьё главное фото ротируется")
    name: str = Field(min_length=1, max_length=255, description="Название теста")
    vendor_code: str = Field(default="", max_length=255, description="Артикул продавца")
    impression_budget: int = Field(
        default=DEFAULT_IMPRESSION_BUDGET,
        ge=100,
        le=10_000_000,
        description="Сколько рекламных показов должен набрать вариант до смены фото",
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
    impression_budget: int
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
