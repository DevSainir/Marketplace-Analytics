<script setup>
/**
 * The headline cards, laid out to fill the left half of the overview.
 *
 * Four as a 2×2 block when bonuses are shown, two stacked when they are not —
 * in both cases the grid stretches to the height of the zone table beside it,
 * so the two halves end on one line. Each card pins its figure to the top and
 * its note to the bottom, so a tall card reads as a card, not as empty space.
 *
 * «С баланса» is spend minus the bonus — the seller's own money, whether the
 * balance or the settlement payout paid it. ДРР от продаж is spend on settled
 * days over settled sales, and says up to which day.
 */
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { dateRu, ratioPct } from '@/modules/advertising/adsFormat'
import { drrOf } from '@/modules/advertising/skuModel'

const props = defineProps({
  totals: { type: Object, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  /** The window, for the spend card's note. */
  period: { type: String, default: '' },
  settledTo: { type: String, default: null },
  /** False when spend and sales are in different currencies. */
  drrComparable: { type: Boolean, default: true },
})

const money = (value) => formatMoney(value, props.currency)
const spend = computed(() => Number(props.totals.spend))
const bonus = computed(() => Number(props.totals.bonus))
const share = (part) => ratioPct(spend.value ? part / spend.value : null)

const drr = computed(() => {
  if (!props.drrComparable) return { value: '—', note: 'реклама и продажи в разных валютах' }
  if (props.totals.sales === null) return { value: '—', note: 'продажи ещё не рассчитаны' }
  return {
    value: ratioPct(drrOf(Number(props.totals.spend_settled), Number(props.totals.sales))),
    note: `продажи по ${dateRu(props.settledTo)}`,
  }
})

const cards = computed(() => [
  { key: 'spend', label: 'Потрачено на рекламу', value: money(spend.value), note: props.period },
  ...(props.showBonus
    ? [
        {
          key: 'own',
          label: 'С баланса',
          value: money(spend.value - bonus.value),
          note: `${share(spend.value - bonus.value)} — ваши деньги`,
        },
        {
          key: 'bonus',
          label: 'Промо-бонусы',
          value: money(bonus.value),
          note: `${share(bonus.value)} — деньги WB`,
        },
      ]
    : []),
  { key: 'drr', label: 'ДРР от продаж', value: drr.value.value, note: drr.value.note },
])
</script>

<template>
  <div
    class="grid h-full gap-sm"
    :class="showBonus ? 'grid-cols-2 grid-rows-2' : 'grid-cols-2 lg:grid-cols-1 lg:grid-rows-2'"
  >
    <div
      v-for="card in cards"
      :key="card.key"
      class="flex flex-col justify-between gap-sm rounded-card border border-border-subtle bg-surface p-md shadow-card"
    >
      <div>
        <div class="text-tiny font-medium uppercase tracking-wider text-muted">
          {{ card.label }}
        </div>
        <div class="mt-xs text-h2 font-bold tabular-nums text-primary">{{ card.value }}</div>
      </div>
      <div class="text-tiny text-muted">{{ card.note }}</div>
    </div>
  </div>
</template>
