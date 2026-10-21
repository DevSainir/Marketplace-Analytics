<script setup>
/**
 * The per-article (or subject, or brand) advertising table — the desktop
 * projection; `AdsSkuCards` is the phone one, fed the same rows.
 *
 * PrimeVue for the sorting and the frozen first column, sorted by «Реклама»
 * to start with: the question the table answers first is "where is the money". The
 * «Итого» is the whole current filter. «Промо-бонусы» sits next to the money
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
  /** Heading of the first column: «Артикул», «Предмет» or «Бренд». */
  labelHeader: { type: String, required: true },
  /** Rows before filtering, for «Итого 12 из 30». `0` hides the «из». */
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
        <DataState kind="empty" layout="bare" text="Ничего не найдено" />
      </template>

      <Column field="label" :header="labelHeader" sortable frozen :footer="foot.label">
        <template #body="{ data }">
          <span class="inline-flex items-center gap-xs">
            <button
              type="button"
              class="inline-flex h-5 w-5 flex-none items-center justify-center rounded-btn text-micro text-muted transition hover:bg-hover hover:text-primary"
              :aria-expanded="Boolean(expanded[data.label])"
              :title="expanded[data.label] ? 'Свернуть зоны показа' : 'По зонам показа'"
              @click="toggle(data.label)"
            >
              <span class="inline-block transition" :class="expanded[data.label] && 'rotate-90'">
                ▶
              </span>
            </button>
            <span>
              <span class="font-medium">{{ formatSku(data.label) }}</span>
              <span v-if="data.n" class="text-muted"> · {{ data.n }}</span>
            </span>
          </span>
        </template>
      </Column>
      <Column field="spend" class="col-num" header="Реклама" sortable :footer="foot.spend">
        <template #body="{ data }">{{ money(data.spend) }}</template>
      </Column>
      <Column v-if="showBonus" field="bonus" class="col-num" sortable :footer="foot.bonus">
        <template #header>
          Промо-бонусы<InfoHint text="Часть рекламы, которую оплатил WB из бонусного пула" />
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-muted': !data.bonus }">
            {{ money(data.bonus) }}
          </span>
        </template>
      </Column>
      <Column field="drr" class="col-num" sortable :footer="foot.drr">
        <template #header>
          ДРР от продаж<InfoHint text="Реклама за рассчитанные дни ÷ продажи за те же дни" />
        </template>
        <template #body="{ data }">
          <span :class="{ 'text-status-negative': showDrr && data.drr > DRR_ALARM }">
            {{ drr(data) }}
          </span>
        </template>
      </Column>
      <Column field="share" class="col-num" sortable :footer="foot.share">
        <template #header>
          <span>Доля</span>
          <InfoHint text="Доля общих рекламных расходов на этот артикул" />
        </template>
        <template #body="{ data }">{{ ratioPct(data.share) }}</template>
      </Column>
      <Column field="orders" class="col-num" header="Заказы" sortable :footer="foot.orders">
        <template #body="{ data }">{{ count(data.orders) }}</template>
      </Column>
      <Column field="sales" class="col-num" sortable :footer="foot.sales">
        <template #header>
          <span>Продажи</span>
          <InfoHint text="Продажи (выкупы) минус возвраты по цене продавца, за рассчитанные дни" />
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
