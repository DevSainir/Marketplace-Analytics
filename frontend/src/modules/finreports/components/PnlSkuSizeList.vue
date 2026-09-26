<script setup>
/**
 * One article's sizes on a phone — the card projection of `PnlSkuSizeTable`.
 *
 * The desktop drill-down is sixteen columns; at 402pt it would be a table
 * inside a card inside a list, scrolled sideways under a finger that is trying
 * to scroll the page. So each size is two lines, like every other record on the
 * phone: the size and what it earned first (margin before ads, the column a
 * seller opens sizes for), then how it sold — units, returns, buyout. The
 * rest of the sixteen stay on the desktop table.
 *
 * Fed the same `/sizes` response as the table: one answer, two projections.
 */
import { money, num, pct, units } from '@/modules/finreports/pnlFormat'
import { amountClass, toneClass } from '@/modules/finreports/pnlThresholds'

defineProps({
  /** @type {object|null} `{ loading, error, data }` for the article, or `null` before the ask. */
  state: { type: Object, default: null },
})
</script>

<template>
  <div class="size-list">
    <p class="size-list__title">Размеры</p>
    <p v-if="!state || state.loading" class="record-note">Считаем размеры…</p>
    <p v-else-if="state.error" class="record-note text-status-negative">{{ state.error }}</p>
    <p v-else-if="!state.data?.rows?.length" class="record-note">
      За этот период у артикула нет строк с размером.
    </p>
    <template v-else>
      <div v-for="size in state.data.rows" :key="size.ts_name" class="size-list__item">
        <div class="size-list__line">
          <span class="font-medium text-primary">{{ size.ts_name || 'Без размера' }}</span>
          <span class="tabular-nums" :class="amountClass(size.margin_before_ads)">
            {{ money(size.margin_before_ads) }}
            <span :class="toneClass('profitPct', size.margin_pct)">{{ pct(size.margin_pct) }}</span>
          </span>
        </div>
        <p class="record-note">
          продано {{ units(size.sold_units) }} · возвр.
          {{ num(size.returned_units) ? units(size.returned_units) : '0' }} · выкуп
          <span :class="toneClass('buyoutPct', size.buyout_pct)">{{ pct(size.buyout_pct) }}</span>
        </p>
      </div>
      <div class="size-list__line size-list__total">
        <span>Итого по размерам</span>
        <span class="tabular-nums">{{ money(state.data.totals.margin_before_ads) }}</span>
      </div>
      <p class="record-note">Маржа без рекламы: WB не даёт рекламу в разрезе размеров.</p>
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

.size-list__total {
  @apply border-t border-border-subtle pt-xs font-semibold text-primary;
}
</style>
