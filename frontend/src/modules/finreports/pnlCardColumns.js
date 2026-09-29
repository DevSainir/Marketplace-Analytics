/**
 * Список артикулов на телефоне: чем сортировать и что показывать под карточкой.
 *
 * Отдельно от компонента, потому что это описание таблицы, а не разметка: у
 * телефонной проекции нет строки заголовков, которую можно нажать, поэтому
 * порядок и подписи приходится задать списком — и этот список длиннее, чем
 * вся остальная логика карточек.
 */
import { money, pct, units } from '@/modules/finreports/pnlFormat'
import { toneClass } from '@/modules/finreports/pnlThresholds'

/** The sort keys worth having without a header row to click. */
export const SORT_KEYS = [
  { key: 'profit', label: 'Чистая прибыль' },
  { key: 'sales', label: 'Продажи' },
  { key: 'sold', label: 'Продажи, шт' },
  { key: 'logistics', label: 'Логистика' },
  { key: 'penalties', label: 'Штрафы' },
  { key: 'advertising', label: 'Реклама' },
  { key: 'cogs', label: 'Себестоимость' },
  { key: 'roi', label: 'ROI' },
  { key: 'saName', label: 'Артикул' },
]

/**
 * The folded-away columns, in the table's own order. `tone` paints the figure
 * when it is outside the bounds in `pnlThresholds` — the same rule the desktop
 * table uses, so the two projections flag the same rows.
 */
export const DETAILS = [
  { label: 'Заказы, шт', get: (r) => units(r.orders) },
  { label: 'Продажи, шт', get: (r) => units(r.sold) },
  {
    label: 'Выкуп, % (временно)',
    get: (r) => pct(r.buyoutPct),
    tone: (r) => toneClass('buyoutPct', r.buyoutPct),
  },
  {
    label: 'Возвраты, %',
    get: (r) => pct(r.returnPct),
    tone: (r) => toneClass('returnPct', r.returnPct),
  },
  { label: 'Средний чек', get: (r) => money(r.averageCheque) },
  { label: 'СПП, %', get: (r) => pct(r.sppPct) },
  {
    label: 'Логистика',
    get: (r) => money(r.logistics),
    sub: (r) => pct(r.logisticsPct),
    subTone: (r) => toneClass('logisticsPct', r.logisticsPct),
  },
  { label: 'Себестоимость', get: (r) => money(r.cogs) },
  {
    label: 'Реклама',
    get: (r) => money(r.advertising),
    sub: (r) => pct(r.advertisingPct),
    subTone: (r) => toneClass('advertisingPct', r.advertisingPct),
  },
  { label: 'Бонусы WB', get: (r) => (r.adBonus ? `−${money(r.adBonus)}` : money(r.adBonus)) },
  { label: 'ROI', get: (r) => pct(r.roi), tone: (r) => toneClass('roi', r.roi) },
]
