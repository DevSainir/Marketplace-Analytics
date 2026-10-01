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
 * - «Продажи» — revenue NET of returns at the page's price base (`priceBase.js`),
 *   which the card names, then the units bought out and returned. Units are
 *   net too: «488 шт» over a net figure while 69 of them came back made the
 *   money and the count disagree.
 * - «Логистика» — the full delivery bill and its share of sales at the same
 *   a customer has no such page, so the card shows them neither link nor word.
 * - «Прочие удержания» — WB's own «Прочие удержания» line (Σ deduction), with
 *   the advertising (ВБ.Продвижение) share it is mostly made of.
 * - «Себестоимость» — the seller's own cost of the sold units; flags how many
 *   SKUs still have no cost, because the profit is understated by exactly them.
 * - «Итого к оплате» — what actually reaches the bank account after every
 *   withholding, minus any marked SKUs (WB's own name for this total).
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'
import { PRICE_BASES, atBase, shareOf, usePriceBase } from '@/modules/finreports/priceBase'

const props = defineProps({
  /** @type {object} The report's exclusion-aware `dashboard` object. */
  dashboard: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const base = usePriceBase()

const money = (value) => formatMoney(value, props.currency)
const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(Number(value)))

const cards = computed(() => {
  const d = props.dashboard
  const excluded = Number(d.excluded_count) || 0
  const sales = atBase(base(), d.sales, d.paid)
  const returned = Number(d.returned_units) || 0
  const logisticsShare = `${pct(shareOf(d.logistics, sales))} от продаж`
  return [
    {
      key: 'sales',
      label: 'Продажи',
      value: money(sales),
      caption: PRICE_BASES.find((b) => b.key === base())?.caption ?? '',
      sub: `${formatNumber(Number(d.sold_units) - returned)} шт · возвраты ${formatNumber(returned)} шт`,
      hint: 'За вычетом возвратов. Цена селлера — ваша цена до СПП («Цена розничная с учётом согласованной скидки»). Цена реализации — сколько заплатил покупатель после СПП; это «Продажа» в отчёте WB. Возвраты — выкупленные и затем возвращённые товары, не отмены заказов.',
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
      sub: d.filtered
        ? `в т.ч. реклама: ${money(d.advertising)} · на весь счёт`
        : `в т.ч. реклама: ${money(d.advertising)}`,
      hint: 'Реклама, подписка и транзитные удержания WB списывает счётом на весь аккаунт без привязки к SKU — поэтому эта карточка не меняется от фильтра или исключения артикулов.',
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
      label: 'Итого к оплате',
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
  <!-- Two-up wraps «2 403 199 KGS» onto a second line at 402pt and leaves the
       fifth card alone on its own row; one column keeps each figure whole. -->
  <section
    class="grid grid-cols-2 gap-md phone:grid-cols-1 phone:gap-sm md:grid-cols-3 xl:grid-cols-5"
  >
    <component
      :is="card.to ? RouterLink : 'div'"
      v-for="card in cards"
      :key="card.key"
      :to="card.to ?? undefined"
      class="rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
      :class="card.to ? 'transition hover:border-action' : ''"
    >
      <div class="text-tiny font-medium uppercase tracking-wide text-muted">{{ card.label }}</div>
      <div class="mt-xs text-h2 font-bold" :class="card.accent ? 'text-action' : 'text-primary'">
        {{ card.value }}
      </div>
      <div v-if="card.caption" class="mt-xs text-tiny text-muted">{{ card.caption }}</div>
      <div
        class="mt-xs text-tiny"
        :class="card.warn ? 'text-status-warning' : 'text-muted'"
        :title="card.hint || undefined"
      >
        {{ card.sub }}
      </div>
    </component>
  </section>
</template>
