<script setup>
/**
 * The headline cards — one slim row across the full width of the block.
 *
 * Four with bonuses shown, two without; each is a label over its figure with
 * the qualifier on the same line, so the row stays one line of numbers high
 * and the zone table under it starts within reach.
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
    note: `по ${dateRu(props.settledTo)}`,
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
          note: `${share(spend.value - bonus.value)} — ваши`,
        },
        {
          key: 'bonus',
          label: 'Промо-бонусы',
          value: money(bonus.value),
          note: `${share(bonus.value)} — от WB`,
        },
      ]
    : []),
  { key: 'drr', label: 'ДРР от продаж', value: drr.value.value, note: drr.value.note },
])
</script>

<template>
  <div class="grid grid-cols-2 gap-sm" :class="showBonus ? 'lg:grid-cols-4' : ''">
    <div
      v-for="card in cards"
      :key="card.key"
      class="rounded-card border border-border-subtle bg-surface px-md py-sm shadow-card"
    >
      <div class="text-micro font-medium uppercase tracking-wider text-muted">{{ card.label }}</div>
      <div class="flex flex-wrap items-baseline gap-x-sm">
        <span class="text-h3 font-bold tabular-nums text-primary">{{ card.value }}</span>
        <span class="text-tiny text-muted">{{ card.note }}</span>
      </div>
    </div>
  </div>
</template>
