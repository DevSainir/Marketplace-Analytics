"""HTTP schemas of the A/B-tests module.

What crosses the boundary in both directions. Ratios are computed on read and
serialised as ``null`` where their denominator is empty — the SPA renders «—»
for those, the way WB's own result table does, because 0 % and "not measured
yet" are different answers.
"""

# ruff: noqa: RUF001 — field descriptions are the Russian labels the SPA
# renders, and they sit next to Latin terms ("CTR", "WB"), which makes the
# confusable-character check fire on ordinary Cyrillic. The constants that are
# actually compared against WB responses live elsewhere and are covered by
# tests/unit/finreports/test_wb_labels_are_pure_cyrillic.py.
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

    A single-bound mode refuses the other bound rather than quietly ignoring
    it: sending ``slot_minutes`` with ``trigger_mode="impressions"`` is a 422,
    not a silently dropped field. ``trigger_mode="either"`` is the mode that
    takes both, because it is the mode that reads both — whichever is reached
    first ends the turn.
    """

    nm_id: int = Field(gt=0, description="Артикул WB, чьё главное фото ротируется")
    name: str = Field(min_length=1, max_length=255, description="Название теста")
    trigger_mode: TriggerMode = Field(
        default=TriggerMode.IMPRESSIONS,
        description="Что двигает ротацию: показы, время или что наступит раньше",
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Показов на вариант. Режимы «по показам» и «показы и время»",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Минут на вариант. Режимы «по времени» и «показы и время»",
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
    the test already has. The bound rule is checked against the *resolved*
    mode — the one in the body if it names one, otherwise the stored one — so
    "set slot_minutes on a test that is still counting impressions" is refused
    even though the body never mentions a mode, while a test in режиме
    «either» takes either field on its own. That check needs the stored test, so it
    happens in the service rather than here.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger_mode: TriggerMode | None = Field(
        default=None, description="Сменить режим: показы, время или оба сразу"
    )
    impression_budget: int | None = Field(
        default=None,
        ge=100,
        le=10_000_000,
        description="Показов на вариант. Режимы «по показам» и «показы и время»",
    )
    slot_minutes: int | None = Field(
        default=None,
        ge=5,
        le=20_160,
        description="Минут на вариант. Режимы «по времени» и «показы и время»",
    )


class CampaignTotals(BaseModel):
    """What one advertising campaign brought the test, over all of its photos.

    The branches under each figure of «Итог по тесту». They sum to the figure
    above them, because both are summed from the same interval rows — the split
    happens where the counters arrive, not where they are drawn.
    """

    campaign_id: int = Field(description="Идентификатор кампании в WB; 0 — данные до разделения")
    name: str = Field(description="Название кампании в кабинете WB")
    kind: str = Field(
        description="Тип кампании: uni | manual_search | manual_shelves | cpc | unknown"
    )

    views: int = Field(description="Показы, которые дала эта РК")
    clicks: int = Field(description="Переходы в карточку с этой РК")
    atbs: int = Field(description="Добавления в корзину с этой РК")
    orders: int = Field(description="Заказы с этой РК")
    spend: Decimal = Field(description="Расход этой РК за засчитанные отрезки")

    click_through: Decimal | None = Field(description="CTR этой РК по всему тесту, %")
    add_to_cart: Decimal | None = Field(description="Корзины / клики этой РК, %")
    order_rate: Decimal | None = Field(description="Заказы / корзины этой РК, %")


class VariantCampaignMetrics(BaseModel):
    """One photo's figures inside ONE campaign.

    Everything is recomputed within the campaign, the gap to the leader
    included: a photo can lead «Единая» and trail «CPC», and that is precisely
    what the whole-test row cannot show.
    """

    campaign_id: int = Field(description="Кампания, в которой посчитаны эти числа")

    views: int
    clicks: int
    atbs: int
    orders: int
    spend: Decimal

    click_through: Decimal | None = Field(description="Доля переходов в карточку, %")
    add_to_cart: Decimal | None = Field(description="Доля добавлений в корзину, %")
    order_rate: Decimal | None = Field(description="Доля оформлений заказов, %")

    ctr_gap: Decimal | None = Field(description="Отставание CTR от лучшего В ЭТОЙ РК, п.п.")
    ctr_result: Decimal | None = Field(description="То же отставание в процентах")

    rounds_played: int = Field(
        default=0,
        description=(
            "В скольких кругах эта РК приносила показы этому фото. "
            "Не круги теста: РК, выключенная на четвёртом круге, сыграла четыре."
        ),
    )


class ExposureCampaignCounts(BaseModel):
    """What one turn earned from one campaign.

    Absent for a campaign that earned nothing in the turn — the timeline reads
    «эта РК работала в этом круге» off the presence of an entry.
    """

    campaign_id: int
    views: int = 0
    clicks: int = 0
    click_through: Decimal | None = Field(default=None, description="CTR за эту установку, %")


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
    is_original: bool = Field(
        default=False,
        description="Главное фото теста — эталон, с которым сравниваются остальные; позиция 0",
    )
    is_excluded: bool = Field(
        default=False,
        description="Убрано из ротации: в следующих кругах не участвует, метрики сохранены",
    )

    rounds_played: int = Field(default=0, description="В скольких кругах фото участвовало")
    ctr_gap: Decimal | None = Field(
        default=None, description="Отставание CTR от лучшего, в процентных пунктах"
    )
    ctr_result: Decimal | None = Field(
        default=None, description="То же отставание относительно лучшего, в процентах"
    )

    click_through: Decimal | None = Field(description="Доля переходов в карточку, %")
    add_to_cart: Decimal | None = Field(description="Доля добавлений в корзину, %")
    order_rate: Decimal | None = Field(description="Доля оформлений заказов, %")

    views: int = Field(description="Показы карточки в выдаче")
    clicks: int = Field(description="Переходы в карточку")
    atbs: int = Field(description="Добавления в корзину")
    orders: int = Field(description="Оформления заказов")
    spend: Decimal = Field(description="Расход на рекламу за дни этого варианта")

    days_measured: int = Field(description="Сколько полных дней зачтено этому фото")

    campaigns: list[VariantCampaignMetrics] = Field(
        default_factory=list,
        description=(
            "Те же метрики отдельно по каждой рекламной кампании, в порядке "
            "«Единая, Руч. поиск, Руч. полки, CPC». Пусто у теста без измерений."
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
    because for a live test it ends at «сейчас» and any stored value of it is
    stale the moment it is serialised.
    """

    views: int = Field(description="Показы карточки в рекламе за весь тест")
    clicks: int = Field(description="Переходы в карточку за весь тест")
    atbs: int = Field(description="Добавления в корзину за весь тест")
    orders: int = Field(description="Оформления заказов за весь тест")
    spend: Decimal = Field(description="Расход рекламы на этот артикул за измеренные отрезки")

    click_through: Decimal | None = Field(description="Клики / показы по тесту целиком, %")
    add_to_cart: Decimal | None = Field(description="Корзины / клики по тесту целиком, %")
    order_rate: Decimal | None = Field(description="Заказы / корзины по тесту целиком, %")

    measured_minutes: int = Field(
        description=(
            "Сумма длительностей засчитанных отрезков — время, за которое собраны эти "
            "числа. Меньше времени с запуска на всё, что тест простоял без рекламы или "
            "на паузе."
        )
    )
    windows: int = Field(description="Сколько отрезков опроса зачтено")
    first_window_at: datetime | None = Field(
        default=None, description="Начало самого раннего засчитанного отрезка"
    )
    last_window_at: datetime | None = Field(
        default=None, description="Конец самого позднего засчитанного отрезка — данные по этот час"
    )

    rounds_completed: int = Field(default=0, description="Сколько кругов ротация уже прошла")
    variants_measured: int = Field(default=0, description="Сколько фото успели набрать показы")
    variants_total: int = Field(default=0, description="Сколько фото в тесте")


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
        description=(
            "Когда ротация в последний раз остановилась — пауза или завершение. "
            "Сбрасывается при возобновлении."
        ),
    )
    photo_conflict_at: datetime | None = Field(
        default=None,
        description=(
            "Когда ротация обнаружила на карточке главное фото, которое она не "
            "устанавливала: значит, карточку поменяли вручную. Тест остановлен и сам "
            "не возобновится — трафик с чужого фото ни одному варианту не принадлежит. "
            "null, если такого не было."
        ),
    )
    created_at: datetime

    leader_variant_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Вариант с лучшим CTR среди набравших хотя бы один полный день. "
            "None, пока сравнивать нечего."
        ),
    )


class AbTestDetail(AbTestRead):
    """A test plus the per-photo result table and the log of its turns."""

    variants: list[VariantMetrics] = Field(default_factory=list)
    history: list[ExposureRow] = Field(
        default_factory=list, description="Каждая установка фото, новые сверху"
    )
    rounds_completed: int = Field(default=0, description="Сколько кругов ротация уже прошла")

    active_since: datetime | None = Field(
        default=None,
        description=(
            "Когда текущее фото встало на карточку. Начало отсчёта слота в режиме "
            "«по времени»; null, пока ничего не установлено."
        ),
    )

    summary: AbTestSummary = Field(description="Итог по тесту целиком — сумма строк таблицы")

    campaigns: list[CampaignTotals] = Field(
        default_factory=list,
        description=(
            "Рекламные кампании, которые реально принесли тесту трафик, в порядке "
            "«Единая, Руч. поиск, Руч. полки, CPC». Одна кампания — страница "
            "выглядит как раньше; две и больше — появляются разрез и выбор РК. "
            "Кампания, выключенная посреди теста, остаётся здесь: её показы "
            "никуда не делись."
        ),
    )


class VariantExclusionUpdate(BaseModel):
    """Request body for taking a photo out of the rotation, or putting it back."""

    excluded: bool = Field(description="true — убрать из ротации, false — вернуть")


class ExposureRow(BaseModel):
    """One turn in «История действий»: a photo installed, and what it earned."""

    model_config = ConfigDict(from_attributes=True)

    variant_id: uuid.UUID
    position: int
    is_original: bool
    image_url: str
    round_number: int = Field(description="Круг, к которому относится установка")
    activated_at: datetime = Field(description="Когда WB принял загрузку")
    deactivated_at: datetime | None = Field(default=None, description="Когда фото сняли")
    minutes: int | None = Field(default=None, description="Сколько минут фото простояло")

    views: int = 0
    clicks: int = 0
    click_through: Decimal | None = Field(default=None, description="CTR за эту установку, %")

    campaigns: list[ExposureCampaignCounts] = Field(
        default_factory=list,
        description="Та же установка в разрезе РК; РК без трафика в ней отсутствуют",
    )


class AbTestStatusUpdate(BaseModel):
    """Request body for starting, pausing or cancelling a test."""

    status: str = Field(description="running | paused | cancelled")


class AbTestFinish(BaseModel):
    """Request body for finishing a test: which photo the card keeps."""

    keep_variant_id: uuid.UUID = Field(description="Фото, которое останется на карточке")
