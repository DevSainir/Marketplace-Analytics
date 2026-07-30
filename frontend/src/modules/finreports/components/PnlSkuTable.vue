<script setup>
/**
 * The per-SKU P&L table — the «По артикулам» cut of the report.
 *
 * One row per SKU with the money columns of the reference workbook: units,
 * revenue and СПП, logistics with its share, penalties by WB's own categories,
 * advertising, the payout and the net profit. Percentages are shares of that
 * SKU's net paid revenue.
 *
 * The «Штрафы» cell carries its categories inline (tiny second line) — the
 * category is what tells a seller whether a fine is disputable, and hiding it
 * behind an expander buried exactly the number this module exists to surface.
 *
 * PrimeVue in unstyled/Tailwind mode, matching the monitoring tables: sorting
 * and the frozen article column are the reason.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed, ref, toRefs } from 'vue'

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

const { rows, unallocated } = toRefs(props)

const num = (value) => (value === null || value === undefined ? null : Number(value))

function toRow(r, isBucket = false) {
  return {
    nmId: r.nm_id,
    saName: r.sa_name,
    isBucket,
    orders: num(r.orders_units),
    sold: r.sold_units,
    returned: r.returned_units,
    returnPct: num(r.return_rate_pct),
    sales: num(r.sales_amount),
    sppPct: num(r.spp_pct),
    logistics: num(r.logistics_total),
    logisticsPct: num(r.logistics_pct),
    penalties: num(r.penalties_total),
    penaltyReasons: (r.penalties ?? []).map((p) => ({ reason: p.reason, amount: num(p.amount) })),
    cogs: num(r.cogs),
    advertising: num(r.advertising),
    advertisingPct: num(r.advertising_pct),
    payout: num(r.payout_net),
    profit: num(r.net_profit),
    profitPct: num(r.net_profit_pct),
  }
}

const tableRows = computed(() => {
  const list = rows.value.map((r) => toRow(r))
  if (unallocated.value) list.push(toRow(unallocated.value, true))
  return list
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
</script>

<template>
  <div class="app-datatable rounded-card border border-border-subtle bg-surface shadow-card">
    <div class="flex items-center justify-end gap-sm border-b border-border-subtle px-md py-sm">
      <label class="text-tiny text-muted" for="sku-page-size">Строк на странице:</label>
      <select
        id="sku-page-size"
        :value="rowsPerPage"
        class="rounded-input border border-border-subtle bg-surface px-sm py-xs text-base text-primary"
        @change="setPageSize($event.target.value)"
      >
        <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }}</option>
      </select>
    </div>
    <DataTable
      v-model:first="first"
      :value="tableRows"
      :paginator="tableRows.length > rowsPerPage"
      :rows="rowsPerPage"
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
    </DataTable>
  </div>
</template>
