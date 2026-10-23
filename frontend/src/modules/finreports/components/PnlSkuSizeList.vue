<script setup>
/**
 * One article's sizes on a phone — the card projection of `PnlSkuSizeTable`.
 *
 * The desktop drill-down is sixteen columns; at 402pt it would be a table
 * inside a card inside a list, scrolled sideways under a finger that is trying
 * to scroll the page. So each size is two lines, like every other record on the
 * phone: the size and its revenue first, then how it sold — units, returns,
 * buyout. The rest stay on the desktop table.
 *
 * Fed the same `/sizes` response as the table: one answer, two projections.
 * No "Total": the sizes sum to the article card they open under.
 */
import BusyBar from '@/core/components/BusyBar.vue'
import { pct, units, usePnlMoney } from '@/modules/finreports/pnlFormat'
import { toneClass } from '@/modules/finreports/pnlThresholds'
import { sizeAtBase, usePriceBase } from '@/modules/finreports/priceBase'

defineProps({
  /** @type {object|null} `{ loading, error, data }` for the article, or `null` before the ask. */
  state: { type: Object, default: null },
})

const { money } = usePnlMoney()
const base = usePriceBase()
const revenue = (size) => sizeAtBase(size, base()).revenue
</script>

<template>
  <div class="size-list">
    <p class="size-list__title">Sizes</p>
    <BusyBar v-if="!state || state.loading" label="Loading…" class="py-sm" />
    <p v-else-if="state.error" class="record-note text-status-negative">{{ state.error }}</p>
    <p v-else-if="!state.data?.rows?.length" class="record-note">
      No sizes for this SKU in the period.
    </p>
    <template v-else>
      <div v-for="size in state.data.rows" :key="size.ts_name" class="size-list__item">
        <div class="size-list__line">
          <span class="font-medium text-primary">{{ size.ts_name || 'No size' }}</span>
          <span class="tabular-nums text-primary">{{ money(revenue(size)) }}</span>
        </div>
        <p class="record-note">
          sold {{ units(size.sold_units) }} · returned {{ units(size.returned_units) }} · buyout
          <span :class="toneClass('sizeBuyoutPct', size.buyout_pct)">{{
            pct(size.buyout_pct)
          }}</span>
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped src="./styles/RecordCards.css"></style>
<style scoped>
.size-list {
  @apply border-t border-border-subtle py-xs;
}

.size-list__title {
  @apply py-xs text-tiny font-medium text-muted;
}

.size-list__item + .size-list__item {
  @apply border-t border-border-subtle;
}

.size-list__item {
  @apply py-xs;
}

.size-list__line {
  @apply flex items-baseline justify-between gap-sm text-tiny;
}
</style>
