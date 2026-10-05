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

const store = useAdvertisingStore()

const all = computed(() => toRows(store.data?.skus ?? []))
const options = computed(() => filterOptions(all.value))
const cabinetSpend = computed(() => Number(store.totals?.spend ?? 0))
const rows = computed(() =>
  groupRows(pickRows(all.value, store.filters), store.group, cabinetSpend.value),
)
const total = computed(() => totalRow(rows.value, cabinetSpend.value))
const groupDef = computed(() => AD_GROUPS.find((g) => g.id === store.group))
const filtering = computed(() =>
  Boolean(store.filters.query || store.filters.subject || store.filters.brand),
)
</script>

<template>
  <section>
    <h2 class="mb-md text-h3 font-semibold text-primary">Реклама по {{ groupDef.by }}</h2>
    <AdsSkuToolbar
      v-model:query="store.filters.query"
      v-model:subject="store.filters.subject"
      v-model:brand="store.filters.brand"
      v-model:group="store.group"
      :subjects="options.subjects"
      :brands="options.brands"
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
