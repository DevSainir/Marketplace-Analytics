/**
 * Строки таблицы «По артикулам» вместе с размерами — дерево, развёрнутое в
 * плоский список.
 *
 * Размеры стоят строками прямо под своим артикулом, в тех же колонках: цифра
 * размера читается под цифрой артикула, и сравнить размеры можно, глядя вниз
 * по колонке. Раньше под артикулом раскрывалась отдельная таблица со своими
 * колонками и своим «Итого», которое повторяло строку артикула.
 *
 * Поэтому сортировку и страницы делает этот файл, а не PrimeVue: его сортировка
 * растащила бы размеры от артикула, а его страница отрезает ровно N строк и
 * вытеснила бы артикулы размерами. Здесь сортируются и делятся на страницы
 * только артикулы, а размеры вставляются после.
 */
import { atBase, shareOf } from '@/modules/finreports/priceBase'

const num = (value) => (value === null || value === undefined ? null : Number(value))

/**
 * Артикулы по колонке. Пустое значение — всегда в конце, в какую сторону ни
 * сортируй: «нет данных» не самое маленькое и не самое большое.
 *
 * @param {Array<object>} rows Строки из `toRow`.
 * @param {string|null} field Поле строки.
 * @param {number|null} order 1 — по возрастанию, −1 — по убыванию.
 * @returns {Array<object>} Новый массив; исходный не трогается.
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
 * Один размер в полях строки артикула: колонка берёт одно и то же поле у
 * обоих. Доли полосок — от суммы размеров, она же строка артикула.
 *
 * @param {object} size Строка ответа `/sizes`.
 * @param {{sold: number, sales: number}} whole Суммы по всем размерам.
 * @param {string} base База цены страницы.
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
    penalties: num(size.penalties_total),
    payout: num(size.payout_net),
    soldShare: whole.sold ? sold / whole.sold : 0,
    salesShare: whole.sales > 0 ? Math.max(0, sales / whole.sales) : 0,
  }
}

/** Что стоит под открытым артикулом, пока размеров нет: одна строка-пояснение. */
function noteFor(state) {
  if (!state || state.loading) return 'Загружаем…'
  if (state.error) return state.error
  return 'За этот период у артикула нет строк с размером.'
}

/**
 * Строки одного открытого артикула: его размеры или строка-пояснение.
 *
 * @param {number} nmId Артикул.
 * @param {object|null} state `{loading, error, data}` из стора.
 * @param {string} base База цены страницы.
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
 * Страница таблицы: артикулы страницы, под каждым открытым — его размеры.
 *
 * @param {Array<object>} page Артикулы страницы, уже отсортированные.
 * @param {object} expanded `nmId -> true` для открытых.
 * @param {object} sizes `nmId -> state` из стора.
 * @param {string} base База цены страницы.
 */
export function treeRows(page, expanded, sizes, base) {
  return page.flatMap((row) => {
    const open = row.isSku && !!expanded[row.nmId]
    const article = { ...row, rowKey: `a:${row.nmId}`, isOpen: open }
    return open ? [article, ...childRows(row.nmId, sizes[row.nmId] ?? null, base)] : [article]
  })
}
