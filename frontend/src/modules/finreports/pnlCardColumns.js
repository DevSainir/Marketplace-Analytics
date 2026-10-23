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
  { key: 'profit', label: 'Net profit' },
  { key: 'sales', label: 'Sales' },
  { key: 'sold', label: 'Sales, units' },
  { key: 'logistics', label: 'Logistics' },
  { key: 'penalties', label: 'Penalties' },
  { key: 'advertising', label: 'Advertising' },
  { key: 'advertisingPct', label: 'ACoS (sales)' },
  { key: 'cogs', label: 'Cost price' },
  { key: 'roi', label: 'ROI' },
  { key: 'saName', label: 'SKU' },
]

/**
 * The folded-away columns, in the table's own order. `get(row, f)` takes the
 * page's formatter (`usePnlMoney`). `tone` paints the figure
 * when it is outside the bounds in `pnlThresholds` — the same rule the desktop
 * table uses, so the two projections flag the same rows.
 */
export const DETAILS = [
  { label: 'Orders, units', get: (r) => units(r.orders) },
  { label: 'Sales, units', get: (r) => units(r.sold) },
  {
    label: 'Buyout rate, %',
    get: (r) => pct(r.buyoutPct),
    tone: (r) => toneClass('buyoutPct', r.buyoutPct),
  },
  {
    label: 'Returns, %',
    get: (r) => pct(r.returnPct),
    tone: (r) => toneClass('returnPct', r.returnPct),
  },
  { label: 'Average price', get: (r, f) => f.money(r.averageCheque) },
  { label: 'WB discount, %', get: (r) => pct(r.sppPct) },
  {
    label: 'Logistics',
    get: (r, f) => f.money(r.logistics),
    sub: (r) => pct(r.logisticsPct),
    subTone: (r) => toneClass('logisticsPct', r.logisticsPct, r.priceBase),
  },
  { label: 'Logistics per buyout', get: (r, f) => f.money(r.logisticsPerSale) },
  {
    label: 'Cost price',
    get: (r, f) => (r.uncosted ? 'missing' : f.money(r.cogs)),
    tone: (r) => (r.uncosted ? 'text-status-warning' : ''),
  },
  { label: 'Advertising', get: (r, f) => f.money(r.advertising) },
  {
    label: 'ACoS (sales)',
    get: (r) => pct(r.advertisingPct),
    tone: (r) => toneClass('advertisingPct', r.advertisingPct, r.priceBase),
  },
  {
    label: 'Promo bonuses',
    get: (r, f) => (r.adBonus ? `-${f.money(r.adBonus)}` : f.money(r.adBonus)),
  },
  { label: 'ROI', get: (r) => pct(r.roi), tone: (r) => toneClass('roi', r.roi) },
]
