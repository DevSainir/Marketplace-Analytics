<script setup>
/**
 * The P&L dashboard — four KPI cards over the selected period.
 *
 * Exactly the four figures the seller tracks daily, each with the secondary
 * number that qualifies it:
 *
 * - «Продажи» — what buyers paid (WB's own figure), with units.
 * - «Логистика» — the full delivery bill and its share of sales; links to the
 * - «Себестоимость» — the seller's own cost of the sold units; flags how many
 *   SKUs still have no cost, because the profit is understated by exactly them.
 * - «Перечисление» — Итого к оплате: what actually reaches the bank account
 *   after every withholding.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

const props = defineProps({
  /** @type {object} The report's `totals` row (PnlSkuRow). */
  totals: { type: Object, required: true },
  currency: { type: String, default: '' },
  /** SKUs with sales but no cost on file — the profit's blind spots. */
  uncostedCount: { type: Number, default: 0 },
})

const money = (value) => formatMoney(value, props.currency)
const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(Number(value)))

const cards = computed(() => [
  {
    key: 'sales',
    label: 'Продажи',
    value: money(props.totals.sales_amount),
    sub: `${formatNumber(props.totals.sold_units)} шт, возвраты ${pct(props.totals.return_rate_pct)}`,
    to: null,
  },
  {
    key: 'logistics',
    label: 'Логистика',
    value: money(props.totals.logistics_total),
  },
  {
    key: 'cogs',
    label: 'Себестоимость',
    value: props.totals.cogs === null ? '—' : money(props.totals.cogs),
    sub:
      props.uncostedCount > 0
        ? `без себестоимости: ${props.uncostedCount} SKU →`
        : 'все SKU покрыты',
    to: { name: 'finreports-cost-prices' },
    warn: props.uncostedCount > 0,
  },
  {
    key: 'payout',
    label: 'Перечисление',
    value: money(props.totals.payout_net),
    sub: 'на счёт, после всех удержаний WB',
    to: null,
    accent: true,
  },
])
</script>

<template>
  <section class="grid grid-cols-2 gap-md xl:grid-cols-4">
    <component
      :is="card.to ? RouterLink : 'div'"
      v-for="card in cards"
      :key="card.key"
      :to="card.to ?? undefined"
      class="rounded-card border border-border-subtle bg-surface p-lg shadow-card"
      :class="card.to ? 'transition hover:border-action' : ''"
    >
      <div class="text-tiny font-medium uppercase tracking-wide text-muted">{{ card.label }}</div>
      <div class="mt-xs text-h2 font-bold" :class="card.accent ? 'text-action' : 'text-primary'">
        {{ card.value }}
      </div>
      <div class="mt-xs text-tiny" :class="card.warn ? 'text-status-warning' : 'text-muted'">
        {{ card.sub }}
      </div>
    </component>
  </section>
</template>
