/**
 * The rows of the «По артикулам» table together with their sizes — a tree
 * flattened into a list.
 *
 * Sizes sit as rows right under their article, in the same columns: a size's
 * figure reads under the article's figure, and sizes can be compared by looking
 * down the column. An article used to expand into a separate table with its
 * own columns and its own «Итого», which repeated the article row.
 *
 * That is why this file does the sorting and paging, not PrimeVue: its sorting
 * would pull sizes away from their article, and its page cuts exactly N rows
 * and would push articles out with sizes. Here only articles are sorted and
 * paged, and sizes are inserted afterwards.
 */
import { atBase, shareOf } from '@/modules/finreports/priceBase'
import { perSale } from '@/modules/finreports/usePnlSkuRows'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * Articles by a column. An empty value always goes last, whichever way you
 * sort: «no data» is neither the smallest nor the largest.
 *
 * @param {Array<object>} rows Rows from `toRow`.
 * @param {string|null} field The row field.
 * @param {number|null} order 1 — ascending, −1 — descending.
 * @returns {Array<object>} A new array; the original is left untouched.
 */
export function sortRows(rows, field, order) {
  if (!field || !order) return rows
  const empty = (v) => v === null || v === undefined || v === ''
  return [...rows].sort((a, b) => {
    const x = a[field]
    const y = b[field]
    if (empty(x) || empty(y)) return empty(x) - empty(y)
    const diff =
      typeof x === 'string' || typeof y === 'string'
        ? String(x).localeCompare(String(y), 'ru', { numeric: true })
        : x - y
    return diff * order
  })
}

/**
 * One size in the fields of an article row: a column reads the same field from
 * both. Bar shares are of the sum of sizes, which is the article row.
 *
 * @param {object} size A row of the `/sizes` response.
 * @param {{sold: number, sales: number}} whole Sums over all sizes.
 * @param {string} base The page's price base.
 */
function toSizeRow(size, whole, base) {
  const sold = Number(size.sold_units)
  const returned = Number(size.returned_units)
  const sales = Number(atBase(base, size.revenue_seller_price, size.revenue_paid))
  const net = sold - returned
  return {
    kind: 'size',
    label: size.ts_name,
    priceBase: base,
    sold,
    returnPct: shareOf(returned, sold),
    buyoutPct: num(size.buyout_pct),
    sales,
    averageCheque: net ? sales / net : null,
    logistics: num(size.logistics_total),
    logisticsPct: shareOf(num(size.logistics_total), sales),
    logisticsPerSale: perSale(num(size.logistics_total), sold),
    penalties: num(size.penalties_total),
    payout: num(size.payout_net),
    soldShare: whole.sold ? sold / whole.sold : 0,
    salesShare: whole.sales > 0 ? Math.max(0, sales / whole.sales) : 0,
  }
}

/** What sits under an open article while there are no sizes: one note row. */
function noteFor(state) {
  if (!state || state.loading) return 'Загружаем…'
  if (state.error) return state.error
  return 'За этот период у артикула нет строк с размером.'
}

/**
 * The rows of one open article: its sizes or a note row.
 *
 * @param {number} nmId Article ID.
 * @param {object|null} state `{loading, error, data}` from the store.
 * @param {string} base The page's price base.
 */
export function childRows(nmId, state, base) {
  const sizes = state?.data?.rows ?? []
  if (state?.loading || state?.error || !sizes.length) {
    return [{ kind: 'note', rowKey: `${nmId}:note`, text: noteFor(state), isError: !!state?.error }]
  }
  const sum = (pick) => sizes.reduce((acc, s) => acc + pick(s), 0)
  const whole = {
    sold: sum((s) => Number(s.sold_units)),
    sales: sum((s) => Number(atBase(base, s.revenue_seller_price, s.revenue_paid))),
  }
  return sizes.map((size, i) => ({
    ...toSizeRow(size, whole, base),
    rowKey: `${nmId}:${size.ts_name}`,
    isLast: i === sizes.length - 1,
  }))
}

/**
 * A table page: the page's articles, with its sizes under each open one.
 *
 * @param {Array<object>} page The page's articles, already sorted.
 * @param {object} expanded `nmId -> true` for open ones.
 * @param {object} sizes `nmId -> state` from the store.
 * @param {string} base The page's price base.
 */
export function treeRows(page, expanded, sizes, base) {
  return page.flatMap((row) => {
    const open = row.isSku && !!expanded[row.nmId]
    const article = { ...row, rowKey: `a:${row.nmId}`, isOpen: open }
    return open ? [article, ...childRows(row.nmId, sizes[row.nmId] ?? null, base)] : [article]
  })
}
