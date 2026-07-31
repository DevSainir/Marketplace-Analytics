<script setup>
/**
 * The P&L dashboard — five KPI cards over the selected period.
 *
 * Reads the backend-computed, exclusion-aware `dashboard` object (not `totals`):
 * the four per-SKU cards drop the SKUs the seller marked «Не включать в общий
 * счёт», while «Прочие удержания» is account-level money with no SKU and so is
 * never affected by a mark. All the arithmetic is the backend's — this only
 * formats it.
 *
 * - «Продажи» — what buyers paid, NET of returns (matches WB's finance page),
 *   with gross and the return rate as the qualifying subline.
 * - «Логистика» — the full delivery bill and its share of sales; links to the
 * - «Прочие удержания» — WB's own «Прочие удержания» line (Σ deduction), with
 *   the advertising (ВБ.Продвижение) share it is mostly made of.
 * - «Себестоимость» — the seller's own cost of the sold units; flags how many
 *   SKUs still have no cost, because the profit is understated by exactly them.
 * - «Перечисление» — Итого к оплате: what actually reaches the bank account
 *   after every withholding, minus any marked SKUs.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

const props = defineProps({
  /** @type {object} The report's exclusion-aware `dashboard` object. */
  dashboard: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const money = (value) => formatMoney(value, props.currency)
const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(Number(value)))

const cards = computed(() => {
  const d = props.dashboard
  const excluded = Number(d.excluded_count) || 0
  return [
    {
      key: 'sales',
      label: 'Продажи',
      value: money(d.sales),
      sub: `${formatNumber(d.sold_units)} шт · возвраты ${pct(d.return_rate_pct)} · валовые ${money(d.sales_gross)}`,
      to: null,
    },
    {
      key: 'logistics',
      label: 'Логистика',
      value: money(d.logistics),
    },
    {
      key: 'other',
      label: 'Прочие удержания',
      value: money(d.other_deductions),
      sub: `в т.ч. реклама: ${money(d.advertising)}`,
      to: null,
    },
    {
      key: 'cogs',
      label: 'Себестоимость',
      value: money(d.cogs),
      sub:
        d.uncosted_count > 0 ? `без себестоимости: ${d.uncosted_count} SKU →` : 'все SKU покрыты',
      to: { name: 'finreports-cost-prices' },
      warn: d.uncosted_count > 0,
    },
    {
      key: 'payout',
      label: 'Перечисление',
      value: money(d.payout_net),
      sub:
        excluded > 0 ? `на счёт · исключено ${excluded} SKU` : 'на счёт, после всех удержаний WB',
      to: null,
      accent: true,
    },
  ]
})
</script>

<template>
  <section class="grid grid-cols-2 gap-md md:grid-cols-3 xl:grid-cols-5">
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
