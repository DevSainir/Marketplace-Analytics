<script setup>
/**
 * The per-article (or subject, or brand) advertising table — the desktop
 * level below the ranked list (`AdsSkuRanked`), fed the same rows.
 *
 * PrimeVue for the sorting and the frozen first column, sorted by «Реклама»
 * to start with: the question the table answers first is «где деньги». The
 * «Итого» is the whole current filter. «Промо-бонусы» sits next to the money
 * it is part of and only exists while the page shows bonuses.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed } from 'vue'

import DataState from '@/core/components/DataState.vue'
import { formatMoney, formatNumber, formatSku } from '@/core/utils/format'
import AdsInfoHint from '@/modules/labs/advertising/components/AdsInfoHint.vue'
import { DRR_ALARM, ratioPct } from '@/modules/labs/advertising/adsFormat'

const props = defineProps({
  /** `groupRows` output. */
  rows: { type: Array, required: true },
  /** `totalRow` of the same rows. */
  total: { type: Object, required: true },
  /** Heading of the first column: «Артикул», «Предмет» or «Бренд». */
  labelHeader: { type: String, required: true },
  /** Rows before filtering, for «Итого 12 из 30». `0` hides the «из». */
  ofTotal: { type: Number, default: 0 },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  showDrr: { type: Boolean, default: true },
})

const money = (value) => formatMoney(value, props.currency)
const count = (value) => (value === null ? '—' : formatNumber(value))
const drr = (row) => (props.showDrr ? ratioPct(row.drr) : '—')

const foot = computed(() => ({
  label:
    `Итого ${props.rows.length}` +
    (props.ofTotal && props.rows.length < props.ofTotal ? ` из ${props.ofTotal}` : ''),
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
      :value="rows"
      data-key="label"
      sort-field="spend"
      :sort-order="-1"
      sort-mode="single"
      scrollable
      scroll-height="560px"
    >
      <template #empty>
        <DataState kind="empty" layout="bare" text="Ничего не найдено" />
      </template>

      <Column field="label" :header="labelHeader" sortable frozen :footer="foot.label">
        <template #body="{ data }">
          <span class="font-medium">{{ formatSku(data.label) }}</span>
          <span v-if="data.n" class="text-muted"> · {{ data.n }}</span>
        </template>
      </Column>
      <Column field="spend" header="Реклама" sortable :footer="foot.spend">
        <template #body="{ data }">{{ money(data.spend) }}</template>
      </Column>
      <Column v-if="showBonus" field="bonus" sortable :footer="foot.bonus">
        <template #header>
          <span title="Часть рекламы, которую оплатил WB из бонусного пула">Промо-бонусы</span>
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-muted': !data.bonus }">
            {{ data.bonus ? money(data.bonus) : '—' }}
          </span>
        </template>
      </Column>
      <Column field="drr" sortable :footer="foot.drr">
        <template #header>
          <span title="Реклама за рассчитанные дни ÷ продажи за те же дни">ДРР</span>
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-status-negative': showDrr && data.drr > DRR_ALARM }">
            {{ drr(data) }}
          </span>
        </template>
      </Column>
      <Column field="share" sortable :footer="foot.share">
        <template #header>
          <span>Доля</span>
          <AdsInfoHint text="Доля общих рекламных расходов на этот артикул" />
        </template>
        <template #body="{ data }">{{ ratioPct(data.share) }}</template>
      </Column>
      <Column field="orders" header="Заказы" sortable :footer="foot.orders">
        <template #body="{ data }">{{ count(data.orders) }}</template>
      </Column>
      <Column field="sales" sortable :footer="foot.sales">
        <template #header>
          <span title="Продажи минус возвраты по цене продавца, за рассчитанные дни">Продажи</span>
        </template>
        <template #body="{ data }">{{ data.sales === null ? '—' : money(data.sales) }}</template>
      </Column>
    </DataTable>
  </div>
</template>
