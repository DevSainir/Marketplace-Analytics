<script setup>
/**
 * The per-article (or subject, or brand) advertising table — the desktop
 * projection; `AdsSkuCards` is the phone one, fed the same rows.
 *
 * PrimeVue for the sorting and the frozen first column, sorted by "Spend"
 * to start with: the question the table answers first is "where is the money". The
 * "Total" is the whole current filter. "Promo bonuses" sits next to the money
 * it is part of and only exists while the page shows bonuses.
 *
 * The ▶ beside a row opens its money by display zone (`AdsSkuZones`), the way
 * the P&L opens an article's sizes. The breakdown is already in the payload,
 * so it opens at once.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed, ref } from 'vue'

import DataState from '@/core/components/DataState.vue'
import InfoHint from '@/core/components/InfoHint.vue'
import { formatMoney, formatNumber, formatSku } from '@/core/utils/format'
import AdsSkuZones from '@/modules/advertising/components/AdsSkuZones.vue'
import { DRR_ALARM, ratioPct } from '@/modules/advertising/adsFormat'

const props = defineProps({
  /** `groupRows` output. */
  rows: { type: Array, required: true },
  /** `totalRow` of the same rows. */
  total: { type: Object, required: true },
  /** Heading of the first column: "SKU", "Category", "Brand" or "Group". */
  labelHeader: { type: String, required: true },
  /** Rows before filtering, for "Total · 12 of 30". `0` hides the "of". */
  ofTotal: { type: Number, default: 0 },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  showDrr: { type: Boolean, default: true },
})

/** Open rows, keyed by label — PrimeVue's `expandedRows` shape. */
const expanded = ref({})

function toggle(label) {
  const { [label]: open, ...rest } = expanded.value
  expanded.value = open ? rest : { ...rest, [label]: true }
}

const money = (value) => formatMoney(value, props.currency)
const count = (value) => (value === null ? '—' : formatNumber(value))
const drr = (row) => (props.showDrr ? ratioPct(row.drr) : '—')
/** An SKU row is an article code; a category, brand or group name is printed as named. */
const nameOf = (row) => (row.nmId ? formatSku(row.label) : row.label)

const foot = computed(() => ({
  label:
    `Total · ${props.rows.length}` +
    (props.ofTotal && props.rows.length < props.ofTotal ? ` of ${props.ofTotal}` : ''),
  spend: money(props.total.spend),
  bonus: money(props.total.bonus),
  drr: drr(props.total),
  share: ratioPct(props.total.share),
  orders: count(props.total.orders),
  sales: props.total.sales === null ? '—' : money(props.total.sales),
}))
</script>

<template>
  <div class="app-datatable">
    <DataTable
      v-model:expanded-rows="expanded"
      :value="rows"
      data-key="label"
      sort-field="spend"
      :sort-order="-1"
      sort-mode="single"
      scrollable
      scroll-height="min(40rem, 70vh)"
    >
      <template #empty>
        <DataState kind="empty" layout="bare" text="Nothing found" />
      </template>

      <Column field="label" :header="labelHeader" sortable frozen :footer="foot.label">
        <template #body="{ data }">
          <span class="inline-flex items-center gap-xs">
            <button
              type="button"
              class="inline-flex h-5 w-5 flex-none items-center justify-center rounded-btn text-micro text-muted transition hover:bg-hover hover:text-primary"
              :aria-expanded="Boolean(expanded[data.label])"
              :title="expanded[data.label] ? 'Hide placements' : 'By placement'"
              @click="toggle(data.label)"
            >
              <span class="inline-block transition" :class="expanded[data.label] && 'rotate-90'">
                ▶
              </span>
            </button>
            <span>
              <span class="font-medium">{{ nameOf(data) }}</span>
              <span v-if="data.n" class="text-muted"> · {{ data.n }}</span>
            </span>
          </span>
        </template>
      </Column>
      <Column field="spend" class="col-num" header="Spend" sortable :footer="foot.spend">
        <template #body="{ data }">{{ money(data.spend) }}</template>
      </Column>
      <Column v-if="showBonus" field="bonus" class="col-num" sortable :footer="foot.bonus">
        <template #header>
          Promo bonuses<InfoHint text="The part of the spend WB paid from its bonus pool" />
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-muted': !data.bonus }">
            {{ money(data.bonus) }}
          </span>
        </template>
      </Column>
      <Column field="drr" class="col-num" sortable :footer="foot.drr">
        <template #header>
          ACoS (sales)<InfoHint text="Spend on settled days ÷ sales on the same days" />
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-status-negative': showDrr && data.drr > DRR_ALARM }">
            {{ drr(data) }}
          </span>
        </template>
      </Column>
      <Column field="share" class="col-num" sortable :footer="foot.share">
        <template #header>
          <span>Share</span>
          <InfoHint text="Share of all ad spend that went to this row" />
        </template>
        <template #body="{ data }">{{ ratioPct(data.share) }}</template>
      </Column>
      <Column field="orders" class="col-num" header="Orders" sortable :footer="foot.orders">
        <template #body="{ data }">{{ count(data.orders) }}</template>
      </Column>
      <Column field="sales" class="col-num" sortable :footer="foot.sales">
        <template #header>
          <span>Sales</span>
          <InfoHint text="Sales (buyouts) minus returns at the seller price, over settled days" />
        </template>
        <template #body="{ data }">{{ data.sales === null ? '—' : money(data.sales) }}</template>
      </Column>

      <template #expansion="{ data }">
        <AdsSkuZones
          :zones="data.zones ?? []"
          :spend="data.spend"
          :currency="currency"
          :show-bonus="showBonus"
        />
      </template>
    </DataTable>
  </div>
</template>
