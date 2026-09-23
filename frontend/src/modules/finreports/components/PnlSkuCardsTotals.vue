<script setup>
/**
 * «Итого» под списком карточек — приклеено к низу экрана.
 *
 * Считается по всей выборке, а не по показанным карточкам: список растёт
 * кнопкой «Показать ещё», и сумма, которая меняется от нажатия на неё, — это
 * не итог, а счётчик. Липкое, чтобы не листать сорок карточек до конца ради
 * одной цифры, и с отступом под домашнюю полосу: на телефоне без него итог
 * лежит ровно под ней.
 */
import { formatMoney, formatPercent } from '@/core/utils/format'
import { amountClass } from '@/modules/finreports/pnlThresholds'

defineProps({
  /** @type {object} Строка из `sumRows`. */
  totals: { type: Object, required: true },
})

const money = (value) => (value === null || value === undefined ? '—' : formatMoney(value, ''))
const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(value))
</script>

<template>
  <div class="pnl-cards-totals">
    <span class="text-tiny font-medium uppercase tracking-wider text-muted">
      Итого{{ totals.excludedCount ? ` (без ${totals.excludedCount})` : '' }}
    </span>
    <span class="text-right">
      <span class="block text-base font-semibold" :class="amountClass(totals.profit)">
        {{ money(totals.profit) }}
      </span>
      <span class="block text-tiny text-muted">
        {{ pct(totals.profitPct) }} · {{ money(totals.sales) }}
      </span>
    </span>
  </div>
</template>

<style scoped>
.pnl-cards-totals {
  @apply sticky bottom-0 -mx-md mt-sm flex items-center justify-between gap-sm border-t border-border-subtle bg-surface px-md py-sm;
  padding-bottom: max(theme('spacing.sm'), env(safe-area-inset-bottom));
}
</style>
