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

const count = (value) =>
  Number.isFinite(Number(value)) ? Math.round(Number(value)).toLocaleString('ru-RU') : '—'

const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(Number(value)))

const baseNote = computed(() =>
  props.revenueBase === 'seller' ? 'по цене карточки' : 'по цене реализации',
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
    value: formatMoney(props.kpi.revenue, props.currency),
    note: baseNote.value,
    lead: true,
  },
  {
    key: 'margin',
    label: 'Маржа',
    value: props.kpi.margin === null ? '—' : formatMoney(props.kpi.margin, props.currency),
    note: props.kpi.margin === null ? uncostedNote.value : `${pct(props.kpi.margin_pct)} выручки`,
    lead: true,
    muted: props.kpi.margin === null,
    negative: props.kpi.margin !== null && Number(props.kpi.margin) < 0,
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
  {
    key: 'buyout',
    label: 'Выкуп',
    value: pct(props.kpi.buyout_pct),
    note:
      props.kpi.buyout_counted_pct === null
        ? 'продано к заказано'
        : `счётчик WB ${pct(props.kpi.buyout_counted_pct)}`,
  },
  {
    key: 'cheque',
    label: 'Средний чек',
    value: formatMoney(props.kpi.average_cheque, props.currency),
    note: 'на единицу',
  },
])
</script>

<template>
  <div class="sum-kpis">
    <div
      v-for="card in cards"
      :key="card.key"
      class="sum-kpi"
      :class="{ 'sum-kpi--lead': card.lead }"
    >
      <div class="sum-kpi__label">{{ card.label }}</div>
      <div
        class="sum-kpi__value"
        :class="{ 'sum-kpi__value--muted': card.muted, 'sum-kpi__value--neg': card.negative }"
      >
        {{ card.value }}
      </div>
      <div class="sum-kpi__note">{{ card.note }}</div>
    </div>
  </div>
</template>

<style scoped>
/* One block rather than six cards: hairline gaps over a ruled background, so
   the figures read as a single statement instead of six unrelated tiles. */
.sum-kpis {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 1px;
  background: var(--ui-hairline);
  border-radius: var(--ui-r-md);
  box-shadow: var(--ui-sh-xs);
  overflow: hidden;
}

@media (max-width: 1100px) {
  .sum-kpis {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 640px) {
  .sum-kpis {
    grid-template-columns: repeat(2, 1fr);
  }
}

.sum-kpi {
  padding: 13px 15px 14px;
  background: var(--ui-surface);
}

.sum-kpi--lead {
  background: var(--ui-zebra);
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

.sum-kpi__note {
  margin-top: 2px;
  font-size: 0.6875rem;
  color: var(--ui-faint);
}
</style>
