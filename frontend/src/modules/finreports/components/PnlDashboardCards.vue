<script setup>
/**
 * The P&L dashboard — five KPI cards over the selected period.
 *
 * Reads the backend-computed, exclusion-aware `dashboard` object (not `totals`):
 * the four per-SKU cards drop the SKUs the seller marked "Exclude from total",
 * while "Other deductions" is account-level money with no SKU and so is
 * never affected by a mark. All the arithmetic is the backend's — this only
 * formats it.
 *
 * - "Sales" — revenue NET of returns at the page's price base (`priceBase.js`),
 *   which the card names, then the units bought out and returned. Units are
 *   net too: a gross unit count over a net figure, while part of those units
 *   came back, made the money and the count disagree.
 * - "Logistics" — the full delivery bill and its share of sales at the same
 *   base.
 * - "Other deductions" — WB's own other-deductions line (Σ deduction), with
 *   the advertising (WB's promotion services) share it is mostly made of.
 * - "Cost price" — the seller's own cost of the sold units; flags how many
 *   SKUs still have no cost, because the profit is understated by exactly them,
 *   and says "Fill in →" / "Edit →" — it is the way into the cost editor.
 *   With gaps it is two actions, not one link: "Show them" narrows the table
 *   below to exactly those SKUs (`show-uncosted`), where each can be costed in
 *   place, and "Fill in →" still opens the editor for the Excel route.
 * - "Total payout" — what actually reaches the bank account after every
 *   withholding, minus any marked SKUs (WB's own term for this total).
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import KpiTile from '@/core/components/KpiTile.vue'
import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'
import { skuCount } from '@/modules/finreports/pnlFormat'
import { PRICE_BASES, atBase, shareOf, usePriceBase } from '@/modules/finreports/priceBase'

const props = defineProps({
  /** @type {object} The report's exclusion-aware `dashboard` object. */
  dashboard: { type: Object, required: true },
  currency: { type: String, default: '' },
})

const emit = defineEmits(['show-uncosted'])

const COST_EDITOR = { name: 'finreports-cost-prices' }

const base = usePriceBase()

const money = (value) => formatMoney(value, props.currency)
const pct = formatPercent

const cards = computed(() => {
  const d = props.dashboard
  const excluded = Number(d.excluded_count) || 0
  const sales = atBase(base(), d.sales, d.paid)
  const returned = Number(d.returned_units) || 0
  const logisticsShare = `${pct(shareOf(d.logistics, sales))} of sales`
  return [
    {
      key: 'sales',
      label: 'Sales',
      value: money(sales),
      caption: PRICE_BASES.find((b) => b.key === base())?.caption ?? '',
      sub: `${formatNumber(Number(d.sold_units) - returned)} units · ${formatNumber(returned)} returned`,
      hint: 'Sales minus returns. A return is an item sent back after purchase, not a canceled order.',
      to: null,
    },
    {
      key: 'logistics',
      label: 'Logistics',
      value: money(d.logistics),
      sub: logisticsShare,
      to: null,
    },
    {
      key: 'other',
      label: 'Other deductions',
      value: money(d.other_deductions),
      sub: d.filtered
        ? `incl. advertising: ${money(d.advertising)} · whole invoice`
        : `incl. advertising: ${money(d.advertising)}`,
      hint: 'WB charges these to the whole workspace, not to SKUs, so filters leave this card as it is.',
      to: null,
    },
    {
      key: 'cogs',
      label: 'Cost price',
      value: money(d.cogs),
      sub:
        d.uncosted_count > 0 ? `no cost price: ${skuCount(d.uncosted_count)}` : 'all SKUs costed',
      // The editor's only entrance since "Cost price" left the page header.
      // With gaps the tile carries two actions (below), so it is not a link.
      to: d.uncosted_count > 0 ? null : COST_EDITOR,
      action: d.uncosted_count > 0 ? '' : 'Edit →',
      gaps: d.uncosted_count > 0,
      warn: d.uncosted_count > 0,
    },
    {
      key: 'payout',
      label: 'Total payout',
      value: money(d.payout_net),
      sub:
        excluded > 0
          ? `to the bank · ${skuCount(excluded)} excluded`
          : 'to the bank, after all WB deductions',
      to: null,
      accent: true,
    },
  ]
})
</script>

<template>
  <!-- Two-up wraps "KGS 2,403,199" onto a second line at 402pt and leaves the
       fifth card alone on its own row; one column keeps each figure whole. -->
  <section
    class="grid grid-cols-2 gap-md phone:grid-cols-1 phone:gap-sm md:grid-cols-3 xl:grid-cols-5"
  >
    <KpiTile
      v-for="card in cards"
      :key="card.key"
      :label="card.label"
      :value="card.value"
      :caption="card.caption ?? ''"
      :sub="card.sub ?? ''"
      :sub-warn="Boolean(card.warn)"
      :tone="card.accent ? 'accent' : 'default'"
      :hint="card.hint ?? ''"
      :to="card.to ?? null"
      :action="card.action ?? ''"
    >
      <div v-if="card.gaps" class="mt-sm flex flex-wrap gap-x-md gap-y-xs text-tiny font-medium">
        <button
          type="button"
          class="text-action hover:underline"
          data-testid="show-uncosted"
          @click="emit('show-uncosted')"
        >
          Show them ↓
        </button>
        <RouterLink :to="COST_EDITOR" class="text-action hover:underline">Fill in →</RouterLink>
      </div>
    </KpiTile>
  </section>
</template>
