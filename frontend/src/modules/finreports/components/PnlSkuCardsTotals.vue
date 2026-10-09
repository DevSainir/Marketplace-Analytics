<script setup>
/**
 * «Итого» over the list of cards — first, as on every phone list in the app
 * (the phone-layout skill: «the totals first»).
 *
 * Counted over the whole selection, not the cards shown: the list grows by
 * «Показать ещё», and a sum that changes when that is pressed is a counter,
 * not a total. It used to stick to the bottom of the screen so nobody had to
 * scroll forty cards for one figure; first in the list answers the same need
 * without taking a strip of a phone's screen for good, and reads the same as
 * the advertising and heatmap lists.
 */
import { pct, usePnlMoney } from '@/modules/finreports/pnlFormat'
import { amountClass } from '@/modules/finreports/pnlThresholds'

defineProps({
  /** @type {object} Строка из `sumRows`. */
  totals: { type: Object, required: true },
})

const { money } = usePnlMoney()
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
  @apply mt-md flex items-center justify-between gap-sm border-b border-border-subtle pb-sm;
}
</style>
