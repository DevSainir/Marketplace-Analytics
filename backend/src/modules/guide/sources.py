"""The catalogue: what `guide` captures, how often, and why it is worth a row.

This is the file to read first and the only one to edit when adding a feed. Each
entry carries the measurement that justifies its cadence — every window here was
probed live against WB on 2026-09-12, and the numbers are in
`.claude/skills/wildberries-api/references/`.

**The cadence rule.** Daily when a missed day is a lost day: the feed's window is
short enough that falling behind cannot be made up. Monthly for everything else,
because these feeds serve the account's whole history and a late read costs
nothing. There is deliberately no weekly cadence — the only feed that ever
warranted one (FBS supplies, ~31 days) turned out not to be worth capturing at
all; see below.

What is deliberately NOT here: КИЗы (fiscal receipt numbers), рекламные
пополнения and списания (the second duplicates ``fullstats.spend``), balances
(WB serves no history, so there is nothing to capture), the deleted-card bin,
buyer chat, and the FBS orders feed (``supplier/orders`` already carries FBS
orders — measured, 2 941 of 65 349 rows came from «Склад продавца»). Each was
considered and rejected; re-proposing one should come with a use for it.

**FBS supplies (`marketplace /api/v3/supplies`) were built and then removed**,
2026-09-14, and the reason is worth keeping so nobody adds them again. The feed
is a shipment header with no contents: id, auto-generated name, created/closed
timestamps, a numeric destination office, and `scanDt` filled on 27 of 193 rows.
The contents are unreachable — `/supplies/{id}/orders` is 404, `/trbx` returns
boxes with an empty order list, and `/api/v3/orders?supplyId=` IGNORES the
filter (asked for one supply, got a row from another). And the ids join to
nothing we hold: settlement `gi_id` runs 0-34 410 398 on this account while
supply ids start at 182 918 224 — different entities behind the same `WB-GI-`
prefix, zero overlap on all 193. What survives is a list of dates and office
numbers that answers one question nobody asked. If FBS shipments ever matter,
the feed to capture is `/api/v3/orders` (60-day window), which carries
`supplyId` on each order.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from src.core.config import Settings
from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.modules.guide.services.fetch import (
    CaptureResult,
    CaptureWindow,
    fetch_acceptance_report,
    fetch_claims,
    fetch_documents,
    fetch_feedbacks,
    fetch_goods_return,
    fetch_orders,
    fetch_questions,
    fetch_region_sale,
    fetch_tariffs_pallet,
    fetch_tariffs_return,
)


class GuideCadence(enum.StrEnum):
    """How often a source is walked. One Celery task per value."""

    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass(frozen=True, slots=True)
class GuideSource:
    """One captured feed.

    Attributes:
        key: Stored in ``guide_record.source``. Never rename one — it is the
            join between the rows already captured and the code that captured
            them.
        title: Russian label, for logs and for whoever reads this later.
        cadence: Which scheduled task walks it.
        base_url: Attribute on :class:`~src.core.config.Settings` naming the WB
            host. An attribute rather than a literal so a host move stays a
            config change.
        tokens: Bundle fields to try in order; the first non-empty one is used.
            A tuple because the tariff feeds are account-independent and any
            seller token answers them, while the rest need one specific scope.
        fetch: The walk. Takes a client and the previous watermark, returns rows
            plus the new watermark.
        why: What this would be for, the day someone asks. Written now because
            the answer is much harder to reconstruct later.
        retention: What WB will still serve, as measured. The cadence is only
            defensible next to this number.
    """

    key: str
    title: str
    cadence: GuideCadence
    base_url: str
    tokens: tuple[str, ...]
    fetch: Callable[[WBReferenceClient, CaptureWindow], Awaitable[CaptureResult]]
    why: str
    retention: str

    def token_for(self, bundle: object) -> str:
        """First non-empty token among :attr:`tokens`, or an empty string."""
        for field in self.tokens:
            value = getattr(bundle, field, "")
            if value:
                return str(value)
        return ""

    def host(self, settings: Settings) -> str:
        """Resolve the WB host for this source from settings."""
        return str(getattr(settings, self.base_url))


#: Any seller token answers the tariff calendar — it is the same for every
#: account on the platform.
_ANY_TOKEN: tuple[str, ...] = ("statistics", "analytics", "content")


GUIDE_SOURCES: tuple[GuideSource, ...] = (
    # ---- daily: the window closes faster than a month -------------------
    GuideSource(
        key="claims",
        title="Заявки покупателей на возврат",
        cadence=GuideCadence.DAILY,
        base_url="wb_returns_base_url",
        tokens=("returns",),
        fetch=fetch_claims,
        why=(
            "Единственный источник причины возврата словами покупателя. "
            "Возврат в sale_record — это деньги, goods-return — логистика; "
            "почему товар не подошёл, не говорит ни тот, ни другой."
        ),
        retention=(
            "14 дней. Измерено на трёх аккаунтах 2026-09-12: у всех самая "
            "старая заявка от 2026-08-29. Самое короткое окно из всего, что "
            "отдаёт WB."
        ),
    ),
    GuideSource(
        key="orders",
        title="Лента заказов",
        cadence=GuideCadence.DAILY,
        base_url="wb_statistics_base_url",
        tokens=("statistics",),
        fetch=fetch_orders,
        why=(
            "Отменённые заказы не доходят до отчёта реализации: в нём 241 358 "
            "srid выкупов, а отмен нет вообще. За 188 дней отмен 48 596 — то "
            "есть спрос, который мы сейчас просто не видим. Плюс регион и срок "
            "«заказ → выкуп» поштучно."
        ),
        retention=(
            "188 дней по дате заказа (flag=1: 2026-03-08 отдаёт, 2026-03-07 "
            "пусто), 181 день по курсору lastChangeDate. Один ответ обрезан на "
            "80 000 строках, поэтому обход страничный."
        ),
    ),
    # ---- monthly: WB serves the whole history -----------------------------
    GuideSource(
        key="region_sale",
        title="Продажи по регионам",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_region_sale,
        why=(
            "Город и себестоимость продажи в разрезе географии. Лента заказов "
            "даёт регион, но только на 188 дней назад; здесь история с начала "
            "продаж — единственный способ посмотреть географию глубже."
        ),
        retention="Обрыва нет: отдал 2024-01 при замере. Окно запроса 31 день.",
    ),
    GuideSource(
        key="goods_return",
        title="Возвраты товаров",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_goods_return,
        why=(
            "Логистика возврата: куда едет, в каком статусе, когда завершён. "
            "Не то же, что возврат в sale_record (деньги) и не то же, что "
            "заявка покупателя (претензия)."
        ),
        retention="Обрыва нет: отдал 2024-01. Окно запроса 31 день.",
    ),
    GuideSource(
        key="acceptance",
        title="Платная приёмка",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_analytics_base_url",
        tokens=("analytics",),
        fetch=fetch_acceptance_report,
        why=(
            "В отчёте реализации приёмка есть суммой — 1 670 строк. Сколько "
            "стоила приёмка конкретной поставки, говорит только этот отчёт."
        ),
        retention=(
            "Обрыва нет: отдал 400 дней назад. Окно 31 день, отчёт асинхронный "
            "(создать → опросить → скачать), пустое окно отвечает 204."
        ),
    ),
    GuideSource(
        key="feedbacks",
        title="Отзывы",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_feedbacks_base_url",
        tokens=("feedbacks",),
        fetch=fetch_feedbacks,
        why=(
            "Динамика рейтинга и текст претензий по SKU. Ни один другой "
            "источник не говорит, почему воронка просела после смены партии."
        ),
        retention=(
            "С начала аккаунта: у NEVA 135 099 отзыва начиная с 2024-07-18, "
            "при первом отчёте реализации 2024-07-08. Обрыва нет."
        ),
    ),
    GuideSource(
        key="questions",
        title="Вопросы покупателей",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_feedbacks_base_url",
        tokens=("feedbacks",),
        fetch=fetch_questions,
        why=(
            "Чего не хватает в карточке: о чём спрашивают, того в описании "
            "нет. Слабее отзывов, но берётся тем же токеном и тем же обходом."
        ),
        retention="С начала аккаунта, как и отзывы (у NEVA с 2024-07-19).",
    ),
    GuideSource(
        key="documents",
        title="Документы: УПД, акты, отчёты",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_documents_base_url",
        tokens=("documents",),
        fetch=fetch_documents,
        why=(
            "Опись подписанных оригиналов. В financial_report лежит только "
            "archived_document_id одного отчёта; какие вообще документы WB "
            "выставил — здесь. Для спора это опись доказательств."
        ),
        retention="С начала аккаунта: отдал 2023-10-30. Страница 50 штук.",
    ),
    GuideSource(
        key="tariffs_pallet",
        title="Тарифы паллет",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_common_base_url",
        tokens=_ANY_TOKEN,
        fetch=fetch_tariffs_pallet,
        why=(
            "Коробочные тарифы мы снимаем ежедневно, паллетные — нет. Если "
            "склад когда-нибудь поедет паллетами, история тарифа понадобится "
        ),
        retention=(
            "~70 дней: 2026-07-04 отдаёт 12 складов, 2026-06-29 пусто. "
            "Месячный проход берёт всё окно с запасом."
        ),
    ),
    GuideSource(
        key="tariffs_return",
        title="Тарифы возврата",
        cadence=GuideCadence.MONTHLY,
        base_url="wb_common_base_url",
        tokens=_ANY_TOKEN,
        fetch=fetch_tariffs_return,
        why="Цена обратной логистики по складам — вторая половина стоимости возврата.",
        retention="~70 дней, та же граница, что у паллет: 2026-07-04 есть, 2026-06-29 нет.",
    ),
)


def sources_for(cadence: GuideCadence) -> Sequence[GuideSource]:
    """Every source one scheduled task is responsible for."""
    return tuple(source for source in GUIDE_SOURCES if source.cadence is cadence)


__all__ = [
    "GUIDE_SOURCES",
    "CaptureResult",
    "CaptureWindow",
    "GuideCadence",
    "GuideSource",
    "sources_for",
]
