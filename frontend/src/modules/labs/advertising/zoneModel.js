/**
 * «Куда ушли деньги» as one card per kind of campaign, from the API's flat zones.
 *
 * The backend sends one money row per leaf zone (`services/zones.py`). The
 * page used to draw them as a tree four levels deep and four pies under it;
 * readers lost their place in both. What a seller asks of this block is two
 * questions — which kind of campaign took the money, and where it was shown —
 * so it is now exactly that: a card per kind, its total, and its zones.
 *
 * The payment model (CPM / CPC) is a tag on the card rather than a level of
 * nesting. The order is fixed — единая ставка, the two manual ones, CPC — not
 * by size, so a card is always in the same place from one period to the next; a kind that did not
 * run stays on the row at zero rather than vanishing.
 *
 * Единая ставка has no «Каталог»: WB reports only a unified campaign's search
 * slice, so the rest of it is «Полки» and nothing finer can be told apart.
 */

/** The three zones money is split into, in their fixed colour order. */
export const ZONE_KINDS = [
  { kind: 'search', label: 'Поиск' },
  { kind: 'shelves', label: 'Полки' },
  { kind: 'catalog', label: 'Каталог' },
]

const LABEL = Object.fromEntries(ZONE_KINDS.map((z) => [z.kind, z.label]))

/** One card per campaign kind: the API zones it sums and the kind of each. */
const CARDS = [
  {
    key: 'unified',
    label: 'Единая ставка',
    tag: 'CPM',
    zones: [
      { zone: 'cpm_unified_search', kind: 'search' },
      { zone: 'cpm_unified_shelves', kind: 'shelves' },
    ],
  },
  {
    key: 'manual_search',
    label: 'Ручной поиск',
    tag: 'CPM',
    zones: [
      { zone: 'cpm_manual_search', kind: 'search' },
      { zone: 'cpm_manual_catalog', kind: 'catalog' },
    ],
  },
  {
    key: 'manual_shelves',
    label: 'Ручные полки',
    tag: 'CPM',
    zones: [{ zone: 'cpm_manual_shelves', kind: 'shelves' }],
  },
  {
    key: 'cpc',
    label: 'CPC',
    tag: 'за клики',
    zones: [
      { zone: 'cpc_search', kind: 'search' },
      { zone: 'cpc_shelves', kind: 'shelves' },
    ],
  },
]

/**
 * The cards, and whatever spend has no card.
 *
 * `share` on a card is its part of ALL advertising; `share` on a zone is its
 * part of the card — the two questions the card answers, in that order.
 * Spend whose campaign settings never synced has no kind and no zone, so it is
 * returned apart as `untyped` instead of being forced onto a card.
 *
 * @param {Array<{zone: string, spend: string|number, bonus: string|number}>} zones
 * @returns {{untyped: number, cards: Array<{key: string, label: string, tag: string,
 *   spend: number, bonus: number, share: number|null,
 *   zones: Array<{kind: string, label: string, spend: number, share: number|null}>}>}}
 */
export function bidCards(zones) {
  const byZone = Object.fromEntries(
    zones.map((z) => [z.zone, { spend: Number(z.spend), bonus: Number(z.bonus) }]),
  )
  const total = zones.reduce((sum, z) => sum + Number(z.spend), 0)
  const cards = CARDS.map((card) => {
    const parts = card.zones.map(({ zone, kind }) => ({
      kind,
      label: LABEL[kind],
      ...(byZone[zone] ?? { spend: 0, bonus: 0 }),
    }))
    const spend = parts.reduce((sum, part) => sum + part.spend, 0)
    const bonus = parts.reduce((sum, part) => sum + part.bonus, 0)
    return {
      key: card.key,
      label: card.label,
      tag: card.tag,
      spend,
      bonus,
      share: total ? spend / total : null,
      zones: parts.map(({ kind, label, spend: zoneSpend }) => ({
        kind,
        label,
        spend: zoneSpend,
        share: spend ? zoneSpend / spend : null,
      })),
    }
  })
  return { cards, untyped: byZone.unclassified?.spend ?? 0 }
}
