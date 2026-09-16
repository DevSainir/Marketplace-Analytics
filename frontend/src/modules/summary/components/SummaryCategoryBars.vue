<script setup>
/**
 * «Выручка по категории» — a paired bar per article, subject or brand.
 *
 * Laid out in HTML rather than SVG. The original drew this into a fixed-width
 * viewBox scaled to the container, which magnified every label on a wide screen
 * and stretched a 36px row into something twice that — the block read as
 * enlarged and skewed next to the charts. Rows in CSS keep the type at its
 * declared size at any width, and the bars are the only thing that stretches,
 * which is what a bar is supposed to do.
 *
 * Two bars per row, sharing one scale: share of revenue and share of margin. A
 * negative margin grows leftwards from the same zero, so a loss-maker is a shape
 * rather than a number to notice.
 */
import { computed, ref } from 'vue'

import { formatMoney, formatPercent } from '@/core/utils/format'

const props = defineProps({
  categories: { type: Array, required: true },
  currency: { type: String, default: '' },
})

/** How many rows before the tail folds. */
const HEAD = 10

const expanded = ref(false)

const visible = computed(() =>
  expanded.value ? props.categories : props.categories.slice(0, HEAD),
)

const hiddenCount = computed(() => Math.max(0, props.categories.length - HEAD))

/** One scale for both bars, so their lengths are comparable within a row. */
const scale = computed(() => {
  let high = 0
  let low = 0
  for (const row of visible.value) {
    const revenue = Number(row.revenue_share_pct ?? 0)
    const margin = Number(row.margin_share_pct ?? 0)
    high = Math.max(high, revenue, margin)
    low = Math.min(low, margin)
  }
  const span = high - low || 1
  return { low, span, zero: (-low / span) * 100 }
})

/** Bar geometry as percentages of the track, measured from the shared zero. */
function bar(share) {
  if (share === null || share === undefined) return null
  const value = Number(share)
  const width = (Math.abs(value) / scale.value.span) * 100
  return {
    width: `${Math.max(width, 0.4)}%`,
    left: value < 0 ? `${scale.value.zero - width}%` : `${scale.value.zero}%`,
    negative: value < 0,
  }
}

const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(Number(value)))
</script>

<template>
  <div class="sum-cat">
    <div class="sum-cat__head">
      <span class="sum-cat__legend">
        <span class="sum-cat__swatch sum-cat__swatch--rev"></span>выручка
        <span class="sum-cat__swatch sum-cat__swatch--mar"></span>маржа
      </span>
      <span class="sum-cat__colhead">выручка</span>
      <span class="sum-cat__colhead">маржа</span>
    </div>

    <div v-for="row in visible" :key="row.key" class="sum-cat__row">
      <div class="sum-cat__label" :title="row.label">{{ row.label }}</div>

      <div class="sum-cat__track">
        <span v-if="scale.low < 0" class="sum-cat__zero" :style="{ left: `${scale.zero}%` }"></span>
        <span class="sum-cat__bar sum-cat__bar--rev" :style="bar(row.revenue_share_pct)"></span>
        <span
          v-if="bar(row.margin_share_pct)"
          class="sum-cat__bar sum-cat__bar--mar"
          :class="{ 'sum-cat__bar--neg': bar(row.margin_share_pct).negative }"
          :style="bar(row.margin_share_pct)"
        ></span>
      </div>

      <div class="sum-cat__num">
        {{ formatMoney(row.revenue, currency) }}
        <span class="sum-cat__share">{{ pct(row.revenue_share_pct) }}</span>
      </div>
      <div class="sum-cat__num" :class="{ 'sum-cat__num--neg': Number(row.margin) < 0 }">
        {{ row.margin === null ? '—' : formatMoney(row.margin, currency) }}
        <span class="sum-cat__share">{{ pct(row.margin_pct) }}</span>
      </div>
    </div>

    <button
      v-if="hiddenCount"
      type="button"
      class="ui-chip sum-cat__more"
      @click="expanded = !expanded"
    >
      {{ expanded ? 'Свернуть' : `Показать ещё ${hiddenCount}` }}
    </button>
  </div>
</template>

<style scoped src="@/modules/summary/components/SummaryCategoryBars.css"></style>
