<script setup>
/**
 * The four headline cards: what the window cost, who paid it, and ДРР.
 *
 * The first three are the кабинет's spend HISTORY; ДРР is WB's DEDUCTIONS over
 * revenue, because that is the money the margin carries. The two differ by
 * design and the ДРР note names its own sum so a reader can see both.
 */
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { ratioPct } from '@/modules/labs/advertisement-source/adsFormat'

const props = defineProps({
  /** `spendWindow` for the period. */
  spend: { type: Object, required: true },
  /** `cabinetDrr` for the period at the chosen base. */
  drr: { type: Object, required: true },
  currency: { type: String, default: '' },
  /** «15.07.2026 — 06.09.2026», under the spend card. */
  periodLabel: { type: String, default: '' },
})

const share = (part) => ratioPct(props.spend.total ? part / props.spend.total : null)

const cards = computed(() => [
  {
    key: 'total',
    label: 'Потрачено на рекламу',
    value: formatMoney(props.spend.total, props.currency),
    note: props.periodLabel,
  },
  {
    key: 'balance',
    label: 'С баланса',
    value: formatMoney(props.spend.balance, props.currency),
    note: `${share(props.spend.balance)} — ваши деньги`,
  },
  {
    key: 'promo',
    label: 'Промо-бонусы',
    value: formatMoney(props.spend.promo, props.currency),
    note: `${share(props.spend.promo)} — деньги WB`,
  },
  {
    key: 'drr',
    label: 'ДРР',
    value: ratioPct(props.drr.drr),
    note: `по удержаниям WB, ${formatMoney(props.drr.ads, props.currency)}`,
  },
])
</script>

<template>
  <div class="grid grid-cols-2 gap-sm lg:grid-cols-4">
    <div
      v-for="card in cards"
      :key="card.key"
      class="rounded-card border border-border-subtle bg-surface p-md shadow-card"
    >
      <div class="text-tiny font-medium uppercase tracking-wider text-muted">{{ card.label }}</div>
      <div class="mt-xs text-h2 font-bold tabular-nums text-primary">{{ card.value }}</div>
      <div class="mt-xs text-tiny text-muted">{{ card.note }}</div>
    </div>
  </div>
</template>
