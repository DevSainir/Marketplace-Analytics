/**
 * The «Предметы» / «Бренды» / «Группы» filters of the P&L and the balance —
 * one set of refs and one test, so the two tables can never disagree on what
 * a filter means.
 *
 * Several choices within a filter widen it, the filters together narrow:
 * «Футболки или Шорты» AND «бренд X» AND «в группе Лето». An empty filter is
 * no filter. Rows carry WB's `subject_name`, `brand_name` and `nm_id`.
 */
import { computed, ref } from 'vue'

import { articlesOfGroups, useGroupsStore } from '@/modules/heatmap'

export function useSkuFilters() {
  const groups = useGroupsStore()
  const subjectFilter = ref([])
  const brandFilter = ref([])
  const groupFilter = ref([])

  const active = computed(
    () => subjectFilter.value.length + brandFilter.value.length + groupFilter.value.length > 0,
  )

  /** @param {Array<{subject_name?: string, brand_name?: string, nm_id: number}>} rows */
  function apply(rows) {
    const subjects = new Set(subjectFilter.value)
    const brands = new Set(brandFilter.value)
    const articles = articlesOfGroups(groups.groups, groupFilter.value)
    return rows.filter(
      (r) =>
        (!subjects.size || subjects.has(r.subject_name)) &&
        (!brands.size || brands.has(r.brand_name)) &&
        (!articles || articles.has(r.nm_id)),
    )
  }

  return { subjectFilter, brandFilter, groupFilter, active, apply }
}
