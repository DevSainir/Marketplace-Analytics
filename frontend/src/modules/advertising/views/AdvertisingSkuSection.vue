<script setup>
/**
 * «Реклама по …» — the toolbar and whichever projection the viewport carries.
 *
 * A view-level part rather than a component: it reads the store, which `components/`
 * may not, and it is split from `AdvertisingView` to keep both under the size limit.
 *
 * Two projections, one set of rows: `AdsSkuTable` on a desktop and
 * `AdsSkuCards` below `sm`, both fed the same computed rows so the search,
 * filters and grain apply to both without being wired twice.
 */
import { computed } from 'vue'

import AdsSkuCards from '@/modules/advertising/components/AdsSkuCards.vue'
import AdsSkuTable from '@/modules/advertising/components/AdsSkuTable.vue'
import AdsSkuToolbar from '@/modules/advertising/components/AdsSkuToolbar.vue'
import {
  AD_GROUPS,
  filterOptions,
  groupRows,
  pickRows,
  toRows,
  totalRow,
} from '@/modules/advertising/skuModel'
import { useAdvertisingStore } from '@/modules/advertising/store'
import { articlesOfGroups, useGroupsStore } from '@/modules/heatmap'

const store = useAdvertisingStore()
const groups = useGroupsStore()

const all = computed(() => toRows(store.data?.skus ?? []))
const options = computed(() => filterOptions(all.value))
const cabinetSpend = computed(() => Number(store.totals?.spend ?? 0))
const picked = computed(() =>
  pickRows(all.value, {
    ...store.filters,
    articles: articlesOfGroups(groups.groups, store.filters.groupIds),
  }),
)
const rows = computed(() => groupRows(picked.value, store.group, cabinetSpend.value, groups.groups))
// Over the articles, not the rows: by «Группы» one article can sit in two.
const total = computed(() => totalRow(picked.value, cabinetSpend.value))
const groupDef = computed(() => AD_GROUPS.find((g) => g.id === store.group))
const filtering = computed(() => {
  const { query, subjects, brands, groupIds } = store.filters
  return Boolean(query || subjects.length || brands.length || groupIds.length)
})
</script>

<template>
  <section>
    <h2 class="mb-md text-h3 font-semibold text-primary">Реклама по {{ groupDef.by }}</h2>
    <AdsSkuToolbar
      v-model:query="store.filters.query"
      v-model:subjects="store.filters.subjects"
      v-model:brands="store.filters.brands"
      v-model:group-ids="store.filters.groupIds"
      v-model:group="store.group"
      :subject-options="options.subjects"
      :brand-options="options.brands"
      :filtering="filtering"
      @clear="store.clearFilters"
    />
    <div class="hidden sm:block">
      <AdsSkuTable
        :rows="rows"
        :total="total"
        :label-header="groupDef.col"
        :of-total="store.group === 'sku' ? all.length : 0"
        :currency="store.currency"
        :show-bonus="store.bonusVisible"
        :show-drr="store.drrComparable"
      />
    </div>
    <div class="sm:hidden">
      <AdsSkuCards
        :rows="rows"
        :total="total"
        :currency="store.currency"
        :show-bonus="store.bonusVisible"
        :show-drr="store.drrComparable"
      />
    </div>
  </section>
</template>
