<script setup>
/**
 * The headline cards — one row across the full width of the block.
 *
 * Four with bonuses shown, two without; a label over its figure and nothing
 * else. The qualifiers that used to sit beside the figures (the period, the
 * share, the settled-to day) repeated what the page already says above them.
 *
 * «С баланса» is spend minus WB's bonus — the seller's own money, whether the
 * balance or the settlement payout paid it. «ДРР от продаж» is that own money
 * on the settled days over the settled sales of the same days, across every
 * article: Σ (реклама − бонусы) ÷ Σ продажи, never a mean of per-article ratios.
 * When it cannot be computed the card shows a dash, and says why on hover.
 */
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { ratioPct } from '@/modules/labs/advertising/adsFormat'
import { drrOf } from '@/modules/labs/advertising/skuModel'

const props = defineProps({
  totals: { type: Object, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  /** False when spend and sales are in different currencies. */
  drrComparable: { type: Boolean, default: true },
})

const money = (value) => formatMoney(value, props.currency)
const spend = computed(() => Number(props.totals.spend))
const bonus = computed(() => Number(props.totals.bonus))

const drr = computed(() => {
  if (!props.drrComparable) return { value: '—', why: 'Реклама и продажи в разных валютах' }
  if (props.totals.sales === null) return { value: '—', why: 'Продажи ещё не рассчитаны' }
  if (Number(props.totals.sales) <= 0) return { value: '—', why: 'Возвратов больше, чем продаж' }
  const own = Number(props.totals.spend_settled) - Number(props.totals.bonus_settled)
  return { value: ratioPct(drrOf(own, Number(props.totals.sales))), why: '' }
})

const cards = computed(() => [
  { key: 'spend', label: 'Потрачено на рекламу', value: money(spend.value) },
  ...(props.showBonus
    ? [
        { key: 'own', label: 'С баланса', value: money(spend.value - bonus.value) },
        { key: 'bonus', label: 'Промо-бонусы', value: money(bonus.value) },
      ]
    : []),
  { key: 'drr', label: 'ДРР от продаж', value: drr.value.value, why: drr.value.why },
])
</script>

<template>
  <div class="grid grid-cols-2 gap-sm" :class="showBonus ? 'lg:grid-cols-4' : ''">
    <div
      v-for="card in cards"
      :key="card.key"
      class="rounded-card border border-border-subtle bg-surface px-md py-md shadow-card"
      :title="card.why || null"
    >
      <div class="text-micro font-medium uppercase tracking-wider text-muted">{{ card.label }}</div>
      <div class="mt-xs text-h2 font-bold tabular-nums text-primary">{{ card.value }}</div>
    </div>
  </div>
</template>
