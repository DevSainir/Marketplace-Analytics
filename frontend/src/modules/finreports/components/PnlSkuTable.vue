<script setup>
/**
 * The per-SKU P&L table — the «По артикулам» cut of the report.
 *
 * One row per SKU with the money columns of the reference workbook plus WB's
 * catalogue identity (Артикул WB / Тип предмета / Бренд) and the efficiency
 * ratios (Средний чек, ROI, ROMI). «Продажи» is shown NET of returns, matching
 * WB's finance page; percentages are shares of that net paid revenue.
 *
 * Every figure is the backend's — this component only formats, filters and
 * sorts. Search and the Тип предмета / Бренд filters are purely local over the
 * already-loaded rows (like monitoring's SkuSearchSelect); they never re-fetch
 * and never change the dashboard, which reflects the persisted exclusion marks.
 *
 * The «Штрафы» cell carries its categories inline (tiny second line) — the
 * category is what tells a seller whether a fine is disputable. The rightmost
 * column is the «Не включать в общий счёт» mark; toggling it emits upward so the
 * store can persist it and reload the backend-computed dashboard.
 *
 * PrimeVue in unstyled/Tailwind mode, matching the monitoring tables: sorting
 * and the frozen article column are the reason.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { ref, toRefs, watchEffect } from 'vue'

import PnlSkuTableToolbar from '@/modules/finreports/components/PnlSkuTableToolbar.vue'
import { subsetDashboard, usePnlSkuRows } from '@/modules/finreports/usePnlSkuRows'
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/** Page-size choices. A native select, not the paginator's built-in dropdown:
 *  PrimeVue runs unstyled here and its Select renders collapsed without a
 *  theme, while the app's own convention for pickers is a styled `<select>`. */
const PAGE_SIZES = [50, 100, 150, 200]

const props = defineProps({
  /** @type {Array<object>} `PnlSkuRow` per SKU. */
  rows: { type: Array, default: () => [] },
  /** @type {object|null} The account-level bucket (rendered as the last row). */
  unallocated: { type: Object, default: null },
  currency: { type: String, default: '' },
})

const emit = defineEmits(['toggle-exclusion', 'dashboard-change'])

const { rows, unallocated } = toRefs(props)

// Row shaping + local search/filter live in the composable (keeps this
// component under the size limit).
const { query, subjectFilter, brandFilter, subjects, brands, tableRows, filtered, isFiltering } =
  usePnlSkuRows(rows, unallocated)

// Tell the parent to swap the dashboard to a «по фильтру» subtotal while a
// filter/search is active, and back to the backend one when it clears. Summing
// the visible rows is instant, so the search needs no debounce.
watchEffect(() => {
  emit('dashboard-change', isFiltering.value ? subsetDashboard(filtered.value) : null)
})

const money = (value) => (value === null ? '—' : formatMoney(value, ''))
const pct = (value) => (value === null ? '—' : formatPercent(value))

const rowsPerPage = ref(PAGE_SIZES[0])
/** Reset to the first page on a size change — keeping a stale offset can strand
 *  the view past the last page of the new layout. */
const first = ref(0)

function setPageSize(value) {
  rowsPerPage.value = Number(value)
  first.value = 0
}

/** Dim the excluded rows so the seller sees what the «общий счёт» drops. */
const rowClass = (data) => (data.isExcluded ? 'opacity-50' : '')

function onToggle(data, checked) {
  emit('toggle-exclusion', { nmId: data.nmId, excluded: checked })
}
</script>

<template>
  <div class="app-datatable rounded-card border border-border-subtle bg-surface shadow-card">
    <PnlSkuTableToolbar
      v-model:query="query"
      v-model:subject="subjectFilter"
      v-model:brand="brandFilter"
      :page-size="rowsPerPage"
      :page-sizes="PAGE_SIZES"
      :subjects="subjects"
      :brands="brands"
      @update:page-size="setPageSize"
    />
    <DataTable
      v-model:first="first"
      :value="tableRows"
      :paginator="tableRows.length > rowsPerPage"
      :rows="rowsPerPage"
      :row-class="rowClass"
      sort-mode="single"
      data-key="nmId"
      scrollable
      scroll-height="640px"
    >
      <template #empty>
        <div class="px-md py-xl text-center text-base text-muted">Нет продаж за период</div>
      </template>

      <Column field="saName" header="Артикул" sortable frozen>
        <template #body="{ data }">
          <span :class="data.isBucket ? 'text-muted' : 'font-medium text-primary'">
            {{ data.saName }}
          </span>
        </template>
      </Column>
      <Column field="nmId" header="Артикул WB" sortable>
        <template #body="{ data }">
          <span class="tabular-nums text-muted">{{ data.isBucket ? '—' : data.nmId }}</span>
        </template>
      </Column>
      <Column field="subject" header="Тип предмета" sortable>
        <template #body="{ data }">{{ data.subject || '—' }}</template>
      </Column>
      <Column field="brand" header="Бренд" sortable>
        <template #body="{ data }">{{ data.brand || '—' }}</template>
      </Column>
      <Column field="orders" header="Заказы, шт" sortable>
        <template #body="{ data }">
          {{ data.orders === null ? '—' : formatNumber(data.orders) }}
        </template>
      </Column>
      <Column field="sold" header="Продажи, шт" sortable>
        <template #body="{ data }">{{ formatNumber(data.sold) }}</template>
      </Column>
      <Column field="returnPct" header="Возвраты, %" sortable>
        <template #body="{ data }">{{ pct(data.returnPct) }}</template>
      </Column>
      <Column field="sales" :header="`Продажи, ${currency}`" sortable>
        <template #body="{ data }">{{ money(data.sales) }}</template>
      </Column>
      <Column field="averageCheque" header="Средний чек" sortable>
        <template #body="{ data }">{{ money(data.averageCheque) }}</template>
      </Column>
      <Column field="sppPct" header="СПП, %" sortable>
        <template #body="{ data }">{{ pct(data.sppPct) }}</template>
      </Column>
      <Column field="logistics" header="Логистика" sortable>
        <template #body="{ data }">
          {{ money(data.logistics) }}
          <span v-if="data.logisticsPct !== null" class="text-tiny text-muted">
            ({{ pct(data.logisticsPct) }})
          </span>
        </template>
      </Column>
      <Column field="penalties" header="Штрафы" sortable>
        <template #body="{ data }">
          <template v-if="data.penalties">
            {{ money(data.penalties) }}
            <div
              v-for="p in data.penaltyReasons"
              :key="p.reason"
              class="text-micro leading-tight text-muted"
            >
              {{ p.reason }}: {{ money(p.amount) }}
            </div>
          </template>
          <template v-else>—</template>
        </template>
      </Column>
      <Column field="cogs" header="Себестоимость" sortable>
        <template #body="{ data }">{{ money(data.cogs) }}</template>
      </Column>
      <Column field="advertising" header="Реклама" sortable>
        <template #body="{ data }">
          {{ money(data.advertising) }}
          <span v-if="data.advertisingPct !== null" class="text-tiny text-muted">
            ({{ pct(data.advertisingPct) }})
          </span>
        </template>
      </Column>
      <Column field="roi" header="ROI" sortable>
        <template #body="{ data }">{{ pct(data.roi) }}</template>
      </Column>
      <Column field="romi" header="ROMI" sortable>
        <template #body="{ data }">{{ pct(data.romi) }}</template>
      </Column>
      <Column field="payout" header="К перечислению" sortable>
        <template #body="{ data }">{{ money(data.payout) }}</template>
      </Column>
      <Column field="profit" header="Чистая прибыль" sortable>
        <template #body="{ data }">
          <template v-if="data.profit !== null">
            <span :class="data.profit < 0 ? 'text-status-negative' : 'text-primary'">
              {{ money(data.profit) }}
            </span>
            <span class="text-tiny text-muted"> ({{ pct(data.profitPct) }})</span>
          </template>
          <template v-else>—</template>
        </template>
      </Column>
      <Column field="isExcluded" header="" :sortable="false">
        <template #body="{ data }">
          <label
            v-if="!data.isBucket"
            class="group relative flex items-center justify-center"
            title="Не включать в общий счёт"
          >
            <input
              type="checkbox"
              :checked="data.isExcluded"
              aria-label="Не включать в общий счёт"
              class="h-4 w-4 cursor-pointer rounded border-border-subtle text-action focus:ring-action/20"
              @change="onToggle(data, $event.target.checked)"
            />
            <span
              class="pointer-events-none absolute right-full top-1/2 z-20 mr-sm hidden -translate-y-1/2 whitespace-nowrap rounded-input border border-border-subtle bg-surface px-sm py-xs text-tiny text-primary shadow-card group-hover:block"
            >
              Не включать в общий счёт
            </span>
          </label>
        </template>
      </Column>
    </DataTable>
  </div>
</template>
