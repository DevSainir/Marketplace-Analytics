<script setup>
/**
 * The headline cards.
 *
 * Six figures, no «Прибыль»: this service has no source for taxes, salaries or
 * rent, and a profit computed without them would be a margin wearing a more
 * confident name.
 *
 * The margin card is the one with a state rather than a value. While any
 * settled SKU has no cost price the backend withholds the figure, and the card
 * says which — an em dash alone would read as a rendering fault, and a zero
 * would read as a month that broke even.
 */
import { computed } from 'vue'

import { formatMoney, formatNumber, formatPercent } from '@/core/utils/format'

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
  props.revenueBase === 'seller' ? 'по цене селлера' : 'по цене реализации',
)

/** «1 артикул», «2 артикула», «5 артикулов» — the card names the count. */
function articles(count_) {
  const hundreds = Math.abs(count_) % 100
  const tens = hundreds % 10
  if (hundreds > 10 && hundreds < 20) return 'артикулов'
  if (tens > 1 && tens < 5) return 'артикула'
  if (tens === 1) return 'артикул'
  return 'артикулов'
}

const uncostedNote = computed(
  () => `нет себестоимости: ${props.kpi.uncosted_skus} ${articles(props.kpi.uncosted_skus)}`,
)

const cards = computed(() => [
  {
    key: 'revenue',
    label: 'Выручка',
    value: formatMoney(revenue.value, props.currency),
    note: baseNote.value,
  },
  {
    key: 'margin',
    label: 'Чистая прибыль',
    value: props.kpi.margin === null ? '—' : formatMoney(props.kpi.margin, props.currency),
    note:
      props.kpi.margin === null
        ? uncostedNote.value
        : `${pct(ratio(props.kpi.margin, revenue.value))} выручки`,
    muted: props.kpi.margin === null,
    negative: props.kpi.margin !== null && Number(props.kpi.margin) < 0,
    positive: props.kpi.margin !== null && Number(props.kpi.margin) > 0,
  },
  {
    key: 'sold',
    label: 'Продажи, шт',
    value: count(props.kpi.sold_units),
    note: 'чистых единиц',
  },
  {
    key: 'orders',
    label: 'Заказы, шт',
    value: count(props.kpi.orders),
    note: props.kpi.orders === null ? 'нет данных воронки' : 'штук',
    muted: props.kpi.orders === null,
  },
  // WB's own definition: bought out over ANSWERED deliveries — bought out plus
  // refused — never over orders. An order still in transit belongs to neither
  // half, which is what stops the figure starting near zero and climbing for
  // three weeks after every cohort.
  {
    key: 'buyout',
    label: 'Выкуп',
    value: pct(ratio(props.kpi.buyouts, props.kpi.buyout_decided)),
    // The lag says whose period the figure describes. A window entirely inside
    // it — the page's own default week — has no answered deliveries of its own,
    // so the standing window answers and the card says so rather than passing
    // one period's rate off as another's.
    note:
      props.kpi.buyout_decided === null
        ? 'нет данных воронки'
        : props.kpi.buyout_lagged
          ? 'Усреднённый показатель за предыдущие дни'
          : 'из доставленных',
    hint: props.kpi.buyout_lagged
      ? 'Поскольку заказы за последнюю неделю ещё не успели выкупиться, берётся усреднённое значение за предыдущие две недели.'
      : '',
    muted: props.kpi.buyout_decided === null,
  },
  {
    key: 'penalties',
    label: 'Штрафы и удержания',
    value: formatMoney(props.kpi.penalties, props.currency),
    note: 'без счетов за рекламу',
    negative: Number(props.kpi.penalties) > 0,
  },
  // ДРР is computed here rather than sent, so it follows the price base the
  // reader picked: the same advertising is a different share of the seller's
  // price and of the after-СПП one.
  {
    key: 'drr',
    label: 'ДРР от продаж',
    // A window that returned more than it sold has no meaningful ДРР.
    value: pct(revenue.value > 0 ? ratio(props.kpi.ad_spend, revenue.value) : null),
    note: props.kpi.ad_spend === null ? 'нет данных рекламы' : 'реклама к выручке',
    muted: props.kpi.ad_spend === null,
  },
])
</script>

<template>
  <div class="sum-kpis">
    <div v-for="card in cards" :key="card.key" class="sum-kpi">
      <div class="sum-kpi__label">{{ card.label }}</div>
      <div
        class="sum-kpi__value"
        :class="{
          'sum-kpi__value--muted': card.muted,
          'sum-kpi__value--neg': card.negative,
          'sum-kpi__value--pos': card.positive,
        }"
      >
        {{ card.value }}
      </div>
      <div class="sum-kpi__note">
        {{ card.note }}
        <!-- The explanation rides the note rather than the value: a card whose
             number came from a different period has to say so, and there is no
             room to say it in full under a figure. -->
        <span v-if="card.hint" class="sum-kpi__hint" tabindex="0" role="note">
          <svg viewBox="0 0 16 16" aria-hidden="true" class="sum-kpi__icon">
            <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4" />
            <circle cx="8" cy="4.6" r="0.95" fill="currentColor" />
            <path d="M8 7.2v5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
          <span class="ui-glass ui-glass--pop sum-kpi__tip">{{ card.hint }}</span>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped src="@/modules/summary/components/SummaryKpis.css"></style>
