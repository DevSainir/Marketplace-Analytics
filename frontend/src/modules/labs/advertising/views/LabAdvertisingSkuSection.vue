<script setup>
/**
 * «Реклама по …» — the filter row, the ranked list, and the table behind it.
 *
 * A view-level part rather than a component: it reads the store, which `components/`
 * may not, and it is split from `LabAdvertisingView` to keep both under the size limit.
 *
 * The kit puts a table on the last level only, so the list leads and the full
 * PrimeVue table — every column, any sort — opens below it on request. Both
 * are fed the same computed rows, so the search, filters and grain apply to
 * both without being wired twice. The table stays off phones, where the list
 * already is the whole answer.
 */
import { computed, ref } from 'vue'

import AdsSkuRanked from '@/modules/labs/advertising/components/AdsSkuRanked.vue'
import AdsSkuTable from '@/modules/labs/advertising/components/AdsSkuTable.vue'
import AdsSkuToolbar from '@/modules/labs/advertising/components/AdsSkuToolbar.vue'
import {
  AD_GROUPS,
  filterOptions,
  groupRows,
  pickRows,
  toRows,
  totalRow,
} from '@/modules/labs/advertising/skuModel'
import { useLabAdvertisingStore } from '@/modules/labs/advertising/store'

const store = useLabAdvertisingStore()
const tableOpen = ref(false)

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
  <section class="band">
    <div class="app-container stack">
      <h2 class="t-display">Реклама по {{ groupDef.by }}</h2>
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
      <AdsSkuRanked
        :rows="rows"
        :total="total"
        :currency="store.currency"
        :show-drr="store.drrComparable"
      />
      <div class="more more--wide">
        <button
          type="button"
          class="link-btn"
          :aria-expanded="tableOpen"
          @click="tableOpen = !tableOpen"
        >
          {{ tableOpen ? 'Скрыть таблицу' : 'Все колонки — таблицей' }}
        </button>
      </div>
      <div v-if="tableOpen" class="more--wide">
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
    </div>
  </section>
</template>
