/**
 * The article list on a phone: what to sort by and what to show under a card.
 *
 * Kept apart from the component because it describes the table, not markup: the
 * phone projection has no header row to click, so the order and the captions
 * have to be given as a list — and that list is longer than all the rest of the
 * card logic.
 */
import { pct, units } from '@/modules/finreports/pnlFormat'
import { toneClass } from '@/modules/finreports/pnlThresholds'

/** The sort keys worth having without a header row to click. */
export const SORT_KEYS = [
  { key: 'profit', label: 'Чистая прибыль' },
  { key: 'sales', label: 'Продажи' },
  { key: 'sold', label: 'Продажи, шт' },
  { key: 'logistics', label: 'Логистика' },
  { key: 'penalties', label: 'Штрафы' },
  { key: 'advertising', label: 'Реклама' },
  { key: 'advertisingPct', label: 'ДРР от продаж' },
  { key: 'cogs', label: 'Себестоимость' },
  { key: 'roi', label: 'ROI' },
  { key: 'saName', label: 'Артикул' },
]

/**
 * The folded-away columns, in the table's own order. `get(row, f)` takes the
 * page's formatter (`usePnlMoney`). `tone` paints the figure
 * when it is outside the bounds in `pnlThresholds` — the same rule the desktop
 * table uses, so the two projections flag the same rows.
 */
export const DETAILS = [
  { label: 'Заказы, шт', get: (r) => units(r.orders) },
  { label: 'Продажи, шт', get: (r) => units(r.sold) },
  {
    label: 'Выкуп, %',
    get: (r) => pct(r.buyoutPct),
    tone: (r) => toneClass('buyoutPct', r.buyoutPct),
  },
  {
    label: 'Возвраты, %',
    get: (r) => pct(r.returnPct),
    tone: (r) => toneClass('returnPct', r.returnPct),
  },
  { label: 'Средний чек', get: (r, f) => f.money(r.averageCheque) },
  { label: 'СПП, %', get: (r) => pct(r.sppPct) },
  {
    label: 'Логистика',
    get: (r, f) => f.money(r.logistics),
    sub: (r) => pct(r.logisticsPct),
    subTone: (r) => toneClass('logisticsPct', r.logisticsPct, r.priceBase),
  },
  { label: 'Логистика на 1 выкуп', get: (r, f) => f.money(r.logisticsPerSale) },
  {
    label: 'Себестоимость',
    get: (r, f) => (r.uncosted ? 'нет' : f.money(r.cogs)),
    tone: (r) => (r.uncosted ? 'text-status-warning' : ''),
  },
  { label: 'Реклама', get: (r, f) => f.money(r.advertising) },
  {
    label: 'ДРР от продаж',
    get: (r) => pct(r.advertisingPct),
    tone: (r) => toneClass('advertisingPct', r.advertisingPct, r.priceBase),
  },
  {
    label: 'Промо-бонусы',
    get: (r, f) => (r.adBonus ? `-${f.money(r.adBonus)}` : f.money(r.adBonus)),
  },
  { label: 'ROI', get: (r) => pct(r.roi), tone: (r) => toneClass('roi', r.roi) },
]
