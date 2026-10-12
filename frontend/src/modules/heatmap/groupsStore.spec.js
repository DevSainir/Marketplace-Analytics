import { describe, expect, it, vi } from 'vitest'

import { UNGROUPED, UNNAMED, splitBy, useGroupsReadable } from '@/modules/heatmap/groupsStore'

/** The grants the fake members store answers with; set per test. */
let granted = []
vi.mock('@/modules/profile', () => ({
  useMembersStore: () => ({ canReach: (key) => granted.includes(key) }),
}))

const ITEMS = [
  { id: 1, subject: 'Брюки', brand: 'X' },
  { id: 2, subject: 'Шорты', brand: '' },
  { id: 3, subject: 'Брюки', brand: 'X' },
]
const how = (groups = []) => ({
  nmId: (item) => item.id,
  subject: (item) => item.subject,
  brand: (item) => item.brand,
  groups,
})
const view = (buckets) => buckets.map((b) => [b.label, b.items.map((item) => item.id)])

describe('splitBy', () => {
  it('buckets by subject or brand, an empty name under «(не указан)»', () => {
    expect(view(splitBy(ITEMS, 'subject', how()))).toEqual([
      ['Брюки', [1, 3]],
      ['Шорты', [2]],
    ])
    expect(view(splitBy(ITEMS, 'brand', how()))).toEqual([
      ['X', [1, 3]],
      [UNNAMED, [2]],
    ])
  })

  it('puts an item in every group it is in and the rest under «Без группы»', () => {
    const groups = [
      { id: 'a', name: 'Лето', nm_ids: [1, 2] },
      { id: 'b', name: 'Хиты', nm_ids: [1] },
      { id: 'c', name: 'Пустая', nm_ids: [99] },
    ]

    expect(view(splitBy(ITEMS, 'group', how(groups)))).toEqual([
      ['Лето', [1, 2]],
      ['Хиты', [1]],
      [UNGROUPED, [3]],
    ])
  })
})

describe('useGroupsReadable — who may read the groups', () => {
  it('lets in a manager holding P&L alone — the filter is on that page too', () => {
    granted = ['finreports']

    expect(useGroupsReadable().value).toBe(true)
  })

  it('lets in a manager holding «Сводка» alone', () => {
    granted = ['summary']

    expect(useGroupsReadable().value).toBe(true)
  })

  it('keeps out a manager with no page that carries groups', () => {
    granted = ['monitoring', 'ab_tests']

    expect(useGroupsReadable().value).toBe(false)
  })
})
