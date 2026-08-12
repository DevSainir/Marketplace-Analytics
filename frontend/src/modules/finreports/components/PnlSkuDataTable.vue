<script setup>
/**
 * The per-SKU P&L as a table — the desktop projection of `PnlSkuTable`.
 *
 * One row per SKU with the money columns of the reference workbook plus WB's
 * catalogue identity (Артикул WB / Тип предмета / Бренд) and the efficiency
 * ratios (Средний чек, ROI, ROMI). «Продажи» is shown NET of returns, matching
 * WB's finance page; percentages are shares of that net paid revenue.
 *
 * The «Штрафы» cell carries its categories inline (tiny second line) — the
 * category is what tells a seller whether a fine is disputable. The rightmost
 * column is the «Не включать в общий счёт» mark; toggling it emits upward so the
 * store can persist it and reload the backend-computed dashboard.
 *
 * PrimeVue in unstyled/Tailwind mode, matching the monitoring tables: sorting
 * and the frozen article column are the reason. Split out of `PnlSkuTable` when
 * the phone card list joined it there — eighteen column definitions and a
 * projection switch are two responsibilities, and the pair broke the file-size
 * rule the moment they shared a file.
 *
 * Every figure is the backend's; this only formats.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { ref } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

/** Page-size choices. A native select, not the paginator's built-in dropdown:
 *  PrimeVue runs unstyled here and its Select renders collapsed without a
 *  theme, while the app's own convention for pickers is a styled `<select>`. */
defineProps({
  /** @type {Array<object>} Flattened rows from `usePnlSkuRows`, already filtered. */
  rows: { type: Array, default: () => [] },
  currency: { type: String, default: '' },
  rowsPerPage: { type: Number, default: 50 },
})

const emit = defineEmits(['toggle-exclusion'])

const money = (value) => (value === null ? '—' : formatMoney(value, ''))
const pct = (value) => (value === null ? '—' : formatPercent(value))

/** Reset to the first page on a size change — keeping a stale offset can strand
 *  the view past the last page of the new layout. */
const first = ref(0)

defineExpose({ first })

/** Dim the excluded rows so the seller sees what the «общий счёт» drops. */
const rowClass = (data) => (data.isExcluded ? 'opacity-50' : '')

function onToggle(data, checked) {
  emit('toggle-exclusion', { nmId: data.nmId, excluded: checked })
}
</script>

<template>
  <DataTable
    v-model:first="first"
    :value="rows"
    :paginator="rows.length > rowsPerPage"
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
    <Column field="returnPct" sortable>
      <template #header>
        <span
          title="Выкупленные товары, которые покупатель затем вернул (не отмены заказов): доля от выкупленных штук."
        >
          Возвраты, %
        </span>
      </template>
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
</template>
