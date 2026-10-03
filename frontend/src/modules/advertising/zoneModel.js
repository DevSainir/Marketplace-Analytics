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
 * which nobody measured. The row says where the money is instead.
 *
 * Each leaf names its `kind` — search, shelves or catalogue — so the table can
 * mark it in the same colour the pies give that zone.
 */

/** @typedef {{zone?: string, key?: string, label: string, caption?: string, kind?: string, children?: Node[]}} Node */

/** @type {Node[]} */
const TREE = [
  {
    key: 'cpm',
    label: 'CPM',
    caption: 'оплата за показы',
    children: [
      {
        key: 'manual',
        label: 'Ручная ставка',
        children: [
          {
            key: 'manual_search',
            label: 'Ручной поиск',
            children: [
              { zone: 'cpm_manual_search', label: 'Поиск', kind: 'search' },
              { zone: 'cpm_manual_catalog', label: 'Каталог', kind: 'catalog' },
            ],
          },
          {
            key: 'manual_shelves',
            label: 'Ручные полки',
            children: [{ zone: 'cpm_manual_shelves', label: 'Полки', kind: 'shelves' }],
          },
        ],
      },
      {
        key: 'unified',
        label: 'Единая ставка',
        children: [
          { zone: 'cpm_unified_search', label: 'Поиск', kind: 'search' },
          { zone: 'cpm_unified_shelves', label: 'Полки', kind: 'shelves' },
          { key: 'unified_catalog', label: 'Каталог', kind: 'catalog', unknown: true },
        ],
      },
    ],
  },
  {
    key: 'cpc',
    label: 'CPC',
    caption: 'оплата за клики',
    children: [
      { zone: 'cpc_search', label: 'Поиск', kind: 'search' },
      { zone: 'cpc_shelves', label: 'Полки', kind: 'shelves' },
    ],
  },
  { zone: 'unclassified', label: 'Без типа' },
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
 * `id` is the row's path from the root and `ancestors` the ids above it, which
 * is what lets the table fold a branch without the model knowing about it.
 *
 * @param {Array<{zone: string, spend: string|number, bonus: string|number}>} zones
 * @returns {Array<{id: string, ancestors: string[], label: string, depth: number,
 *   group: boolean, kind: string, unknown: boolean, spend: number, bonus: number,
 *   share: number|null}>}
 */
export function zoneRows(zones) {
  const byZone = Object.fromEntries(
    zones.map((z) => [z.zone, { spend: Number(z.spend), bonus: Number(z.bonus) }]),
  )
  const total = zones.reduce((sum, z) => sum + Number(z.spend), 0)
  const rows = []
  const walk = (node, ancestors, parentSpent) => {
    const { spend, bonus } = money(node, byZone)
    // The unified catalogue row rides on its parent: shown whenever единая
    // ставка spent anything, since that is exactly when its absence matters.
    if (node.unknown ? !parentSpent : !spend) return
    const id = [...ancestors, node.zone ?? node.key].join('/')
    rows.push({
      id,
      ancestors,
      label: node.label,
      caption: node.caption ?? '',
      depth: ancestors.length,
      group: Boolean(node.children),
      kind: node.kind ?? '',
      unknown: Boolean(node.unknown),
      spend,
      bonus,
      share: total && !node.unknown ? spend / total : null,
    })
    for (const child of node.children ?? []) walk(child, [...ancestors, id], spend > 0)
  }
  for (const node of TREE) walk(node, [], true)
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
