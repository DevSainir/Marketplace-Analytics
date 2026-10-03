/**
 * The «На что ушли» tree and the «Зоны показов» pies, from the API's flat zones.
 *
 * The backend sends one money row per leaf zone (`services/zones.py`); the
 * hierarchy is presentation, so it lives here:
 *
 *   CPM ─ Ручная ставка ─ Ручной поиск ─ Поиск / Каталог
 *       │               └ Ручные полки ─ Полки
 *       └ Единая ставка ─ Поиск / Полки / Каталог
 *   CPC ─ Поиск / Полки
 *
 * Единая ставка's «Каталог» is a row with no money on purpose. WB reports only
 * the search slice of a unified campaign, so its catalogue is inside «Полки»
 * and cannot be taken out; printing a zero would say «в каталоге не крутились»,
 * which nobody measured.
 */

/** Why the unified catalogue row has no figure. */
export const UNIFIED_CATALOG_HINT =
  'WB не отделяет каталог от полок у единой ставки — он входит в «Полки»'

/** @typedef {{zone?: string, key?: string, label: string, hint?: string, children?: Node[]}} Node */

/** @type {Node[]} */
const TREE = [
  {
    key: 'cpm',
    label: 'CPM',
    children: [
      {
        key: 'manual',
        label: 'Ручная ставка',
        children: [
          {
            key: 'manual_search',
            label: 'Ручной поиск',
            children: [
              { zone: 'cpm_manual_search', label: 'Поиск' },
              { zone: 'cpm_manual_catalog', label: 'Каталог' },
            ],
          },
          {
            key: 'manual_shelves',
            label: 'Ручные полки',
            children: [{ zone: 'cpm_manual_shelves', label: 'Полки' }],
          },
        ],
      },
      {
        key: 'unified',
        label: 'Единая ставка',
        children: [
          { zone: 'cpm_unified_search', label: 'Поиск' },
          { zone: 'cpm_unified_shelves', label: 'Полки', hint: 'включая каталог' },
          { key: 'unified_catalog', label: 'Каталог', hint: UNIFIED_CATALOG_HINT, unknown: true },
        ],
      },
    ],
  },
  {
    key: 'cpc',
    label: 'CPC',
    children: [
      { zone: 'cpc_search', label: 'Поиск' },
      { zone: 'cpc_shelves', label: 'Полки' },
    ],
  },
  { zone: 'unclassified', label: 'Без типа', hint: 'настройки кампании ещё не загружены' },
]

/** Money of a node: a leaf's own, a group's the sum of its children. */
function money(node, byZone) {
  if (node.unknown) return { spend: 0, bonus: 0 }
  if (node.zone) return byZone[node.zone] ?? { spend: 0, bonus: 0 }
  return node.children.reduce(
    (acc, child) => {
      const part = money(child, byZone)
      return { spend: acc.spend + part.spend, bonus: acc.bonus + part.bonus }
    },
    { spend: 0, bonus: 0 },
  )
}

/**
 * The tree flattened into table rows, depth-first; branches that spent nothing
 * are left out so the table shows the campaigns the кабинет actually runs.
 *
 * @param {Array<{zone: string, spend: string|number, bonus: string|number}>} zones
 * @returns {Array<{key: string, label: string, depth: number, group: boolean,
 *   unknown: boolean, hint: string, spend: number, bonus: number, share: number|null}>}
 */
export function zoneRows(zones) {
  const byZone = Object.fromEntries(
    zones.map((z) => [z.zone, { spend: Number(z.spend), bonus: Number(z.bonus) }]),
  )
  const total = zones.reduce((sum, z) => sum + Number(z.spend), 0)
  const rows = []
  const walk = (node, depth, parentSpent) => {
    const { spend, bonus } = money(node, byZone)
    // The unified catalogue row rides on its parent: shown whenever единая
    // ставка spent anything, since that is exactly when its absence matters.
    if (node.unknown ? !parentSpent : !spend) return
    rows.push({
      key: node.zone ?? node.key,
      label: node.label,
      depth,
      group: Boolean(node.children),
      unknown: Boolean(node.unknown),
      hint: node.hint ?? '',
      spend,
      bonus,
      share: total && !node.unknown ? spend / total : null,
    })
    for (const child of node.children ?? []) walk(child, depth + 1, spend > 0)
  }
  for (const node of TREE) walk(node, 0, true)
  return rows
}

/** The three zones the pies split money into, in their fixed colour order. */
export const PIE_ZONES = [
  { key: 'search', label: 'Поиск' },
  { key: 'shelves', label: 'Полки' },
  { key: 'catalog', label: 'Каталог' },
]

/** Which pie and which slice each API zone feeds. */
const PIE_OF = {
  cpm_manual_search: ['manual', 'search'],
  cpm_manual_catalog: ['manual', 'catalog'],
  cpm_manual_shelves: ['manual', 'shelves'],
  cpm_unified_search: ['unified', 'search'],
  cpm_unified_shelves: ['unified', 'shelves'],
  cpc_search: ['cpc', 'search'],
  cpc_shelves: ['cpc', 'shelves'],
}

const PIES = [
  { key: 'all', label: 'Вся реклама' },
  { key: 'manual', label: 'Ручная ставка' },
  { key: 'unified', label: 'Единая ставка', note: 'каталог внутри полок' },
  { key: 'cpc', label: 'CPC' },
]

/**
 * Four pies — all advertising, ручная, единая, CPC — each split by zone.
 *
 * Unclassified money is in no pie: it has no zone. A pie that spent nothing is
 * dropped rather than drawn as an empty ring.
 *
 * @returns {Array<{key: string, label: string, note: string, total: number,
 *   parts: Array<{key: string, label: string, value: number}>}>}
 */
export function zonePies(zones) {
  const sums = Object.fromEntries(
    PIES.map((pie) => [pie.key, { search: 0, shelves: 0, catalog: 0 }]),
  )
  for (const row of zones) {
    const target = PIE_OF[row.zone]
    if (!target) continue
    const value = Number(row.spend)
    sums[target[0]][target[1]] += value
    sums.all[target[1]] += value
  }
  return PIES.map((pie) => {
    const parts = PIE_ZONES.map((z) => ({ ...z, value: sums[pie.key][z.key] })).filter(
      (part) => part.value > 0,
    )
    return {
      key: pie.key,
      label: pie.label,
      note: pie.note ?? '',
      total: parts.reduce((sum, part) => sum + part.value, 0),
      parts,
    }
  }).filter((pie) => pie.total > 0)
}
