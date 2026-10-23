<script setup>
/**
 * The headline cards.
 *
 * Six figures, no "Profit": this service has no source for taxes, salaries or
 * rent, and a profit computed without them would be a margin wearing a more
 * confident name.
 *
 * The margin card is the one with a state rather than a value. While any
 * settled SKU has no cost price the backend withholds the figure, and the card
 * says which — an em dash alone would read as a rendering fault, and a zero
 * would read as a month that broke even.
 */
import { computed } from 'vue'

import KpiTile from '@/core/components/KpiTile.vue'
import { formatMoney, formatNumber, formatPercent, plural } from '@/core/utils/format'

const props = defineProps({
  kpi: { type: Object, required: true },
  currency: { type: String, default: '' },
  /** Which price the revenue cards are denominated in. */
  revenueBase: { type: String, default: 'paid' },
})

/** Revenue at the selected base — both travel, so switching costs nothing. */
const revenue = computed(() =>
  Number(props.revenueBase === 'seller' ? props.kpi.revenue_seller : props.kpi.revenue_paid),
)

/** A ratio of two figures the payload already carries, as a percentage. */
function ratio(part, whole) {
  if (part === null || part === undefined || !whole) return null
  return (Number(part) / Number(whole)) * 100
}

const count = (value) =>
  formatNumber(value === null || value === undefined ? value : Math.round(value))
const pct = formatPercent

const baseNote = computed(() =>
  props.revenueBase === 'seller' ? 'at seller price' : 'at customer price',
)

/** "no cost price: 1 SKU", "… 5 SKUs" — the card names the count. */
const uncostedNote = computed(() => {
  const n = props.kpi.uncosted_skus
  return `no cost price: ${n} ${plural(n, ['SKU', 'SKUs'])}`
})

const cards = computed(() => [
  {
    key: 'revenue',
    label: 'Revenue',
    value: formatMoney(revenue.value, props.currency),
    note: baseNote.value,
  },
  {
    key: 'margin',
    label: 'Net profit',
    value: props.kpi.margin === null ? '—' : formatMoney(props.kpi.margin, props.currency),
    note:
      props.kpi.margin === null
        ? uncostedNote.value
        : `${pct(ratio(props.kpi.margin, revenue.value))} of revenue`,
    muted: props.kpi.margin === null,
    negative: props.kpi.margin !== null && Number(props.kpi.margin) < 0,
    positive: props.kpi.margin !== null && Number(props.kpi.margin) > 0,
  },
  {
    key: 'sold',
    label: 'Sales, units',
    value: count(props.kpi.sold_units),
    note: 'net units',
  },
  {
    key: 'orders',
    label: 'Orders, units',
    value: count(props.kpi.orders),
    note: props.kpi.orders === null ? 'no funnel data' : 'units',
    muted: props.kpi.orders === null,
  },
  // WB's own definition: bought out over ANSWERED deliveries — bought out plus
  // refused — never over orders. An order still in transit belongs to neither
  // half, which is what stops the figure starting near zero and climbing for
  // three weeks after every cohort.
  {
    key: 'buyout',
    label: 'Buyout rate',
    value: pct(ratio(props.kpi.buyouts, props.kpi.buyout_decided)),
    // The lag says whose period the figure describes. A window entirely inside
    // it — the page's own default week — has no answered deliveries of its own,
    // so the standing window answers and the card says so rather than passing
    // one period's rate off as another's.
    note:
      props.kpi.buyout_decided === null
        ? 'no funnel data'
        : props.kpi.buyout_lagged
          ? 'Average over earlier days'
          : 'of delivered',
    hint: props.kpi.buyout_lagged
      ? "Last week's orders haven't had time to be bought out, so this is the average of the two weeks before."
      : '',
    muted: props.kpi.buyout_decided === null,
  },
  {
    key: 'penalties',
    label: 'Penalties and deductions',
    value: formatMoney(props.kpi.penalties, props.currency),
    note: 'excluding ad invoices',
    negative: Number(props.kpi.penalties) > 0,
  },
  // DRR is computed here rather than sent, so it follows the price base the
  // reader picked: the same advertising is a different share of the seller's
  // price and of the after-SPP one.
  {
    key: 'drr',
    label: 'ACoS (sales)',
    // A window that returned more than it sold has no meaningful DRR.
    value: pct(revenue.value > 0 ? ratio(props.kpi.ad_spend, revenue.value) : null),
    note: props.kpi.ad_spend === null ? 'no ad data' : 'ad spend to revenue',
    muted: props.kpi.ad_spend === null,
  },
])
</script>

<template>
  <div class="sum-kpis">
    <KpiTile
      v-for="card in cards"
      :key="card.key"
      class="sum-kpi"
      :label="card.label"
      :value="card.value"
      :sub="card.note ?? ''"
      :tone="
        card.muted ? 'muted' : card.negative ? 'negative' : card.positive ? 'positive' : 'default'
      "
      :hint="card.hint ?? ''"
    />
  </div>
</template>

<style scoped src="@/modules/summary/components/SummaryKpis.css"></style>
