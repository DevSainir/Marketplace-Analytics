/**
 * Synthetic «Остатки по складам» for the sandbox: one `StockDetail` per day of
 * the window, shaped like the backend's `stockDays`.
 *
 * Shaped like a real FBO catalogue rather than drawn uniformly: two Moscow hubs
 * hold most of the stock, a regional band holds tens, a tail holds a few units
 * of the running sizes. Each day is the previous one minus a day of sales plus
 * one supply, so the ribbon shows MOVEMENT — and the tail empties out as the
 * week goes on, so different days carry different warehouse counts, which is
 * the case the grid's per-day columns exist for.
 */

/** `weight` = the warehouse's share of the SKU's stock. */
const WAREHOUSES = [
  { name: 'Коледино', weight: 0.24 },
  { name: 'Электросталь', weight: 0.17 },
  { name: 'Подольск', weight: 0.11 },
  { name: 'Казань', weight: 0.09 },
  { name: 'Краснодар', weight: 0.075 },
  { name: 'Тула', weight: 0.06 },
  { name: 'Санкт-Петербург Уткина Заводь', weight: 0.055 },
  { name: 'Екатеринбург - Испытателей 14г', weight: 0.045 },
  { name: 'Невинномысск', weight: 0.035 },
  { name: 'Новосибирск', weight: 0.03 },
  { name: 'Рязань (Тюшевское)', weight: 0.025 },
  { name: 'Самара (Новосемейкино)', weight: 0.02 },
  { name: 'Котовск', weight: 0.015 },
  { name: 'Владимир', weight: 0.01 },
  { name: 'Чехов 1', weight: 0.005 },
]

/**
 * How much of the SKU a size holds: a bell over the waist (48 sells most) for
 * «48/170-177»-style sizes, the tall and short heights stocked thinner; a
 * fixed curve for letter sizes.
 */
const LETTER_WEIGHT = { XS: 0.4, S: 0.7, M: 1, L: 1, XL: 0.7, XXL: 0.4 }
const HEIGHT_WEIGHT = { '162-169': 0.45, '170-177': 1, '178-185': 0.7 }

function sizeWeight(techSize) {
  if (LETTER_WEIGHT[techSize]) return LETTER_WEIGHT[techSize]
  const [waist, height] = techSize.split('/')
  const bell = Math.exp(-(((Number(waist) - 48) / 4) ** 2))
  return bell * (HEIGHT_WEIGHT[height] ?? 1)
}

/**
 * @param {object} spec
 * @param {Array<{chrt_id: number, tech_size: string}>} spec.sizes
 * @param {string[]} spec.days ISO days, oldest first
 * @param {() => number} spec.rand seeded generator
 * @param {number} spec.total units across every warehouse and size on day one
 * @returns {Array<{stat_date: string, stock: {cells: object[]}}>}
 */
export function buildStockDays({ sizes, days, rand, total }) {
  const weights = sizes.map((s) => sizeWeight(s.tech_size))
  const weightSum = weights.reduce((a, b) => a + b, 0)

  // Day one. A cell under 3 units is nothing: WB ships in boxes, and a
  // warehouse either holds a size or it does not.
  let cells = sizes.flatMap((size, i) =>
    WAREHOUSES.map((wh) => {
      const q = Math.round((total * wh.weight * weights[i] * (0.6 + rand() * 0.8)) / weightSum)
      return {
        chrt_id: size.chrt_id,
        tech_size: size.tech_size,
        warehouse_name: wh.name,
        quantity: q < 3 ? 0 : q,
      }
    }),
  )

  return days.map((iso, d) => {
    if (d > 0) {
      // A supply lands on one mid-week day at the FULLEST warehouse — the one
      // a seller with a single warehouse (WB's «Склад WB» since 16.08) has, so
      // the lab's one-warehouse views show an arrival too.
      const supplyDay = d === Math.floor(days.length / 2)
      cells = cells.map((cell) => {
        // The last few units of a size go all at once often enough that the
        // tail warehouses drop out of the grid over the week.
        const sold =
          cell.quantity < 6 && rand() < 0.3
            ? cell.quantity
            : Math.round(cell.quantity * rand() * 0.06)
        // Topping up what the warehouse already carries — a supply follows the
        // size curve, it does not seed sizes the warehouse never held.
        const supply =
          supplyDay && cell.warehouse_name === WAREHOUSES[0].name && cell.quantity > 0
            ? Math.round(cell.quantity * (0.3 + rand() * 0.3))
            : 0
        return { ...cell, quantity: Math.max(0, cell.quantity - sold) + supply }
      })
    }
    return { stat_date: iso, stock: { cells } }
  })
}
