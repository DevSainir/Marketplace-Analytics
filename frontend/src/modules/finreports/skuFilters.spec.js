import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useSkuFilters } from '@/modules/finreports/skuFilters'
import { useGroupsStore } from '@/modules/heatmap'

const ROWS = [
  { nm_id: 1, subject_name: 'Брюки', brand_name: 'X' },
  { nm_id: 2, subject_name: 'Шорты', brand_name: 'X' },
  { nm_id: 3, subject_name: 'Брюки', brand_name: 'Y' },
]

describe('useSkuFilters', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useGroupsStore().groups = [
      { id: 'summer', name: 'Лето', nm_ids: [2, 3] },
      { id: 'hits', name: 'Хиты', nm_ids: [1] },
    ]
  })

  const ids = (rows) => rows.map((r) => r.nm_id)

  it('lets everything through while no filter is set', () => {
    const filters = useSkuFilters()
    expect(filters.active.value).toBe(false)
    expect(ids(filters.apply(ROWS))).toEqual([1, 2, 3])
  })

  it('widens within a filter and narrows across filters', () => {
    const filters = useSkuFilters()
    filters.subjectFilter.value = ['Брюки', 'Шорты']
    filters.brandFilter.value = ['X']
    expect(ids(filters.apply(ROWS))).toEqual([1, 2])

    filters.groupFilter.value = ['summer']
    expect(filters.active.value).toBe(true)
    expect(ids(filters.apply(ROWS))).toEqual([2])
  })

  it('takes the articles of every chosen group', () => {
    const filters = useSkuFilters()
    filters.groupFilter.value = ['summer', 'hits']
    expect(ids(filters.apply(ROWS))).toEqual([1, 2, 3])
  })

  it('matches nothing for a chosen group that no longer exists', () => {
    const filters = useSkuFilters()
    filters.groupFilter.value = ['gone']
    expect(filters.apply(ROWS)).toEqual([])
  })
})
