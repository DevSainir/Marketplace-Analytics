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

import { formatMoney, formatPercent } from '@/core/utils/format'

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
  Number.isFinite(Number(value)) ? Math.round(Number(value)).toLocaleString('ru-RU') : '—'

const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(value))

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
    label: 'Маржа',
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
    label: 'Продано',
    value: count(props.kpi.sold_units),
    note: 'чистых единиц',
  },
  {
    key: 'orders',
    label: 'Заказов',
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
          ? 'за 21–7 дней до сегодня'
          : 'выкуплено из решённых',
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
    label: 'Средний ДРР',
    value: pct(ratio(props.kpi.ad_spend, revenue.value)),
    note: props.kpi.ad_spend === null ? 'нет данных рекламы' : 'реклама к выручке, расчётные дни',
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
      <div class="sum-kpi__note">{{ card.note }}</div>
    </div>
  </div>
</template>

<style scoped>
/* Separate tiles, not one ruled block. Seven figures never fill their last row,
   and the shared-background trick left the remainder as an empty slab inside
   the block's own frame — worse than a gap. Each card carries the page's card
   recipe instead: surface, 1px ring, the small shadow. */
.sum-kpis {
  display: grid;
  /* Twelve columns rather than four, so both rows span the full width: the
     first four cards take three columns each, the last three take four. A
     four-column grid left the second row three-quarters wide with a gap where
     the eighth card would be. */
  grid-template-columns: repeat(12, 1fr);
  gap: 10px;
}

.sum-kpi:nth-child(-n + 4) {
  grid-column: span 3;
}

.sum-kpi:nth-child(n + 5) {
  grid-column: span 4;
}

/* Narrower: six columns (three cards and three cards, then one full row), then
   two. The spans are restated because they are what fills each row. */
@media (max-width: 1100px) {
  .sum-kpis {
    grid-template-columns: repeat(6, 1fr);
  }

  .sum-kpi:nth-child(-n + 6) {
    grid-column: span 2;
  }

  .sum-kpi:nth-child(n + 7) {
    grid-column: span 6;
  }
}

@media (max-width: 640px) {
  .sum-kpis {
    grid-template-columns: repeat(2, 1fr);
  }

  .sum-kpi:nth-child(-n + 6),
  .sum-kpi:nth-child(n + 7) {
    grid-column: span 1;
  }

  .sum-kpi:last-child {
    grid-column: span 2;
  }
}

.sum-kpi {
  padding: 13px 15px 14px;
  border-radius: var(--ui-r-md);
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-xs);
}

.sum-kpi__label {
  font-size: 0.625rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ui-faint);
}

.sum-kpi__value {
  /* The app's own face, not the borrowed page's monospace: the design system
     sets KPIs in the body font, and tabular figures are what keeps a column of
     them aligned. */
  margin-top: 5px;
  font-size: 1.3125rem;
  font-weight: 500;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  color: var(--ui-ink);
}

.sum-kpi__value--muted {
  color: var(--ui-faint);
}

.sum-kpi__value--neg {
  color: var(--ui-neg);
}

.sum-kpi__value--pos {
  color: var(--ui-pos);
}

.sum-kpi__note {
  margin-top: 2px;
  font-size: 0.6875rem;
  color: var(--ui-faint);
}
</style>
