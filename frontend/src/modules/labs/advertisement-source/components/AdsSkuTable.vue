<script setup>
/**
 * The per-article (or subject, or brand) advertising table — the desktop
 * projection; `AdsSkuCards` is the phone one, fed the same rows.
 *
 * PrimeVue for the sorting and the frozen first column. Sorted by «Реклама»
 * descending to start with, as the one-pager was: the question the table
 * answers first is «где деньги». The «Итого» is the whole current filter, not
 * a page — there is no paginator; a кабинет has tens of articles, not
 * thousands.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed } from 'vue'

import { formatMoney, formatNumber, formatSku } from '@/core/utils/format'
import { DRR_ALARM, ratioPct } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  /** `groupRows` output — `{label, ads, revenue, orders, promo, drr, n?}`. */
  rows: { type: Array, required: true },
  /** `sumRows` of the same rows. */
  totals: { type: Object, required: true },
  /** Heading of the first column: «Артикул», «Предмет» or «Бренд». */
  labelHeader: { type: String, required: true },
  /** Rows before filtering, for «Итого 12 из 30». `0` hides the «из». */
  ofTotal: { type: Number, default: 0 },
  currency: { type: String, default: '' },
})

const money = (value) => formatMoney(value, props.currency)

const foot = computed(() => ({
  label:
    `Итого ${props.rows.length}` +
    (props.ofTotal && props.rows.length < props.ofTotal ? ` из ${props.ofTotal}` : ''),
  ads: money(props.totals.ads),
  drr: ratioPct(props.totals.drr),
  orders: formatNumber(props.totals.orders),
  revenue: money(props.totals.revenue),
  promo: money(props.totals.promo),
}))
</script>

<template>
  <div class="app-datatable">
    <DataTable
      :value="rows"
      data-key="label"
      sort-field="ads"
      :sort-order="-1"
      sort-mode="single"
      scrollable
      scroll-height="560px"
    >
      <template #empty>
        <div class="px-md py-xl text-center text-base text-muted">Ничего не нашлось</div>
      </template>

      <Column field="label" :header="labelHeader" sortable frozen :footer="foot.label">
        <template #body="{ data }">
          <span class="font-medium">{{ formatSku(data.label) }}</span>
          <span v-if="data.n" class="text-muted"> · {{ data.n }}</span>
        </template>
      </Column>
      <Column field="ads" header="Реклама" sortable :footer="foot.ads">
        <template #body="{ data }">{{ money(data.ads) }}</template>
      </Column>
      <Column field="drr" sortable :footer="foot.drr">
        <template #header><span title="Доля рекламы в выручке">ДРР</span></template>
        <template #body="{ data }">
          <span :class="{ 'text-status-negative': data.drr > DRR_ALARM }">
            {{ ratioPct(data.drr) }}
          </span>
        </template>
      </Column>
      <Column field="orders" header="Заказы" sortable :footer="foot.orders">
        <template #body="{ data }">{{ formatNumber(data.orders) }}</template>
      </Column>
      <Column field="revenue" header="Выручка" sortable :footer="foot.revenue">
        <template #body="{ data }">{{ money(data.revenue) }}</template>
      </Column>
      <Column field="promo" sortable :footer="foot.promo">
        <template #header>
          <span title="Часть открутки, оплаченная бонусами WB, за всё окно файла кабинета">
            Промо-бонусы
          </span>
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-muted': !data.promo }">
            {{ data.promo ? money(data.promo) : '—' }}
          </span>
        </template>
      </Column>
    </DataTable>
  </div>
</template>
