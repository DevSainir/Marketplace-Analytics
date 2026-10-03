<script setup>
/**
 * «На что ушли»: the window's spend per bid type, with the zone split applied.
 *
 * Two or three rows, so no sorting and no paginator — the table exists for its
 * columns, not its length. Below `sm` the same rows become two-line records:
 * eight columns do not fit a phone, and the two that answer the section's
 * question (how much, and how much of it went to search) lead.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { ratioPct } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  /** `kindRows` — one per bid type, largest first. */
  rows: { type: Array, required: true },
  /** `spendWindow` — the «Итого» row. */
  spend: { type: Object, required: true },
  /** `zoneShares` — the overall search share for the «Итого» row. */
  zones: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const money = (value) => formatMoney(value, props.currency)
/** A figure the statistics cannot supply is a dash, never a zero. */
const maybe = (value) => (value === null ? '—' : money(value))

const foot = computed(() => {
  const share = props.zones.share
  return {
    name: 'Итого',
    total: money(props.spend.total),
    part: ratioPct(props.spend.total ? 1 : null),
    balance: money(props.spend.balance),
    promo: money(props.spend.promo),
    search: share === null ? '—' : money(props.spend.total * share),
    rest: share === null ? '—' : money(props.spend.total * (1 - share)),
    share: ratioPct(share),
  }
})
</script>

<template>
  <div class="hidden sm:block">
    <div class="app-datatable">
      <DataTable :value="rows" data-key="name">
        <Column field="name" header="Тип ставки" :footer="foot.name" />
        <Column field="total" header="Потрачено" :footer="foot.total">
          <template #body="{ data }">{{ money(data.total) }}</template>
        </Column>
        <Column field="part" header="Доля" :footer="foot.part">
          <template #body="{ data }">{{ ratioPct(data.part) }}</template>
        </Column>
        <Column field="balance" header="С баланса" :footer="foot.balance">
          <template #body="{ data }">{{ money(data.balance) }}</template>
        </Column>
        <Column field="promo" header="Промо-бонусы" :footer="foot.promo">
          <template #body="{ data }">
            <span :class="{ 'text-muted': !data.promo }">
              {{ data.promo ? money(data.promo) : '—' }}
            </span>
          </template>
        </Column>
        <Column field="search" :footer="foot.search">
          <template #header><span title="Открутка в поисковой выдаче">Поиск</span></template>
          <template #body="{ data }">
            <span :class="{ 'text-muted': data.search === null }">
              {{ data.search === null ? 'нет данных' : money(data.search) }}
            </span>
          </template>
        </Column>
        <Column field="rest" :footer="foot.rest">
          <template #header>
            <span title="Рекомендательные полки, карточка товара и прочие места показа">
              Полки и прочее
            </span>
          </template>
          <template #body="{ data }">{{ maybe(data.rest) }}</template>
        </Column>
        <Column field="share" header="Доля поиска" :footer="foot.share">
          <template #body="{ data }">{{ ratioPct(data.share) }}</template>
        </Column>
      </DataTable>
    </div>
  </div>

  <div
    class="rounded-card border border-border-subtle bg-surface px-md py-sm shadow-card sm:hidden"
  >
    <ul class="divide-y divide-border-subtle">
      <li v-for="row in [...rows, null]" :key="row?.name ?? 'total'" class="py-sm">
        <div class="flex items-baseline justify-between gap-sm">
          <span class="text-base font-medium text-primary">{{ row?.name ?? 'Итого' }}</span>
          <span class="font-semibold tabular-nums text-primary">
            {{ row ? money(row.total) : foot.total }}
          </span>
        </div>
        <div class="flex justify-between gap-sm text-tiny tabular-nums text-muted">
          <span>с баланса {{ row ? money(row.balance) : foot.balance }}</span>
          <span>поиск {{ row ? ratioPct(row.share) : foot.share }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>
