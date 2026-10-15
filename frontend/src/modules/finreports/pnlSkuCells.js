/**
 * Колонки таблицы «По артикулам» и что каждая показывает в строке артикула и в
 * строке размера.
 *
 * Описанием, а не двадцатью шаблонами в разметке: у размера своя версия почти
 * каждой ячейки, и вдвоём они не помещались в `.vue` файл. Ячейка — это
 * `{text, cls, sub, subCls, reasons, bar}`, рисует её `PnlSkuCell`.
 *
 * Колонки без `size` у размера пустые, а не «—»: рекламы, себестоимости и
 * прибыли у размера нет вовсе (WB не делит рекламу по размерам, PNL.md §17.1),
 * а прочерк читается как «не знаем».
 */
import { formatNumber } from '@/core/utils/format'
import { amountClass, toneClass } from '@/modules/finreports/pnlThresholds'
import { pct } from '@/modules/finreports/pnlFormat'

const BLANK = { text: '' }

/** Деньги со долей в скобках — «Логистика». */
function withShare(money, value, share, toneKey, base) {
  return {
    text: money(value),
    sub: share === null || share === undefined ? '' : pct(share),
    subCls: toneClass(toneKey, share, base) || 'text-muted',
  }
}

/**
 * Колонки после «Артикула» в порядке таблицы. `art` и `size` получают строку и
 * форматтер денег и возвращают ячейку.
 */
export const COLUMNS = [
  {
    field: 'nmId',
    header: 'Артикул WB',
    art: (r) => ({ text: r.isSku ? String(r.nmId) : '—', cls: 'tabular-nums text-muted' }),
  },
  { field: 'subject', header: 'Предмет', art: (r) => ({ text: r.subject || '—' }) },
  { field: 'brand', header: 'Бренд', art: (r) => ({ text: r.brand || '—' }) },
  {
    field: 'orders',
    header: 'Заказы, шт',
    num: true,
    art: (r) => ({ text: r.orders === null ? '—' : formatNumber(r.orders) }),
  },
  {
    field: 'sold',
    header: 'Продажи, шт',
    num: true,
    art: (r) => ({ text: formatNumber(r.sold) }),
    size: (s) => ({ text: formatNumber(s.sold), bar: s.soldShare }),
  },
  {
    field: 'buyoutPct',
    header: 'Выкуп, %',
    num: true,
    hint: 'Как в кабинете WB: доля выкупленных заказов, последние 3 недели ещё меняются. У размеров — продано ÷ доставки, поэтому не совпадает.',
    art: (r) => ({ text: pct(r.buyoutPct), cls: toneClass('buyoutPct', r.buyoutPct) }),
    size: (s) => ({ text: pct(s.buyoutPct), cls: toneClass('sizeBuyoutPct', s.buyoutPct) }),
  },
  {
    field: 'returnPct',
    header: 'Возвраты, %',
    num: true,
    hint: 'Сколько проданных штук покупатели потом вернули.',
    art: (r) => ({ text: pct(r.returnPct), cls: toneClass('returnPct', r.returnPct) }),
    size: (s) => ({ text: pct(s.returnPct), cls: toneClass('returnPct', s.returnPct) }),
  },
  {
    field: 'sales',
    header: 'Продажи',
    num: true,
    art: (r, money) => ({ text: money(r.sales) }),
    size: (s, money) => ({ text: money(s.sales), bar: s.salesShare }),
  },
  {
    field: 'averageCheque',
    header: 'Средний чек',
    num: true,
    art: (r, money) => ({ text: money(r.averageCheque) }),
    size: (s, money) => ({ text: money(s.averageCheque) }),
  },
  { field: 'sppPct', header: 'СПП, %', num: true, art: (r) => ({ text: pct(r.sppPct) }) },
  {
    field: 'logistics',
    header: 'Логистика',
    num: true,
    art: (r, money) => withShare(money, r.logistics, r.logisticsPct, 'logisticsPct', r.priceBase),
    size: (s, money) => withShare(money, s.logistics, s.logisticsPct, 'logisticsPct', s.priceBase),
  },
  {
    field: 'logisticsPerSale',
    header: 'Логистика на 1 выкуп',
    num: true,
    hint: 'Вся логистика (туда и обратно) ÷ проданные штуки.',
    art: (r, money) => ({ text: money(r.logisticsPerSale) }),
    size: (s, money) => ({ text: money(s.logisticsPerSale) }),
  },
  {
    field: 'penalties',
    header: 'Штрафы',
    num: true,
    // Причины — не строками в ячейке (строка вырастала на пять строк текста),
    // а «N причин» с карточкой по клику; крупные сверху, сторно внизу.
    art: (r, money) => ({
      text: money(r.penalties),
      reasons: r.penalties
        ? [...r.penaltyReasons]
            .sort((a, b) => b.amount - a.amount)
            .map((p) => ({ reason: p.reason, amount: money(p.amount) }))
        : [],
    }),
    size: (s, money) => ({ text: money(s.penalties) }),
  },
  {
    field: 'cogs',
    header: 'Себестоимость',
    num: true,
    // «нет», not «—»: the cost is not unknown to WB, it is missing from us.
    art: (r, money) =>
      r.uncosted ? { text: 'нет', cls: 'text-status-warning' } : { text: money(r.cogs) },
  },
  {
    field: 'advertising',
    header: 'Реклама',
    num: true,
    art: (r, money) => ({ text: money(r.advertising) }),
  },
  {
    field: 'advertisingPct',
    header: 'ДРР от продаж',
    num: true,
    hint: 'Какая доля продаж ушла на рекламу.',
    art: (r) => ({
      text: pct(r.advertisingPct),
      cls: toneClass('advertisingPct', r.advertisingPct, r.priceBase),
    }),
  },
  {
    field: 'adBonus',
    header: 'Промо-бонусы',
    num: true,
    art: (r, money) =>
      r.adBonus
        ? { text: `-${money(r.adBonus)}`, cls: 'text-status-positive' }
        : { text: money(r.adBonus) },
  },
  {
    field: 'roi',
    header: 'ROI',
    num: true,
    art: (r) => ({ text: pct(r.roi), cls: toneClass('roi', r.roi) }),
  },
  {
    field: 'payout',
    header: 'К перечислению',
    num: true,
    art: (r, money) => ({ text: money(r.payout) }),
    size: (s, money) => ({ text: money(s.payout) }),
  },
  {
    field: 'profit',
    header: 'Чистая прибыль',
    num: true,
    art: (r, money) =>
      r.profit === null
        ? { text: '—' }
        : {
            text: money(r.profit),
            cls: amountClass(r.profit) || 'text-primary',
            sub: pct(r.profitPct),
            subCls: toneClass('profitPct', r.profitPct, r.priceBase) || 'text-muted',
          },
  },
]

/**
 * Ячейка колонки для строки любого вида.
 *
 * @param {object} column Колонка из `COLUMNS`.
 * @param {object} row Строка артикула, размера или пояснения.
 * @param {(value: unknown) => string} money Форматтер денег страницы.
 */
export function cellOf(column, row, money) {
  if (row.kind === 'size') return column.size ? column.size(row, money) : BLANK
  if (row.kind === 'note') return BLANK
  return column.art(row, money)
}
