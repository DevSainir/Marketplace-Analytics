<script setup>
/**
 * «Выручка по категории» — a paired bar per article, subject or brand.
 *
 * Laid out in HTML rather than SVG. The original drew this into a fixed-width
 * viewBox scaled to the container, which magnified every label on a wide screen
 * and stretched a 36px row into something twice that. Rows in CSS keep the type
 * at its declared size at any width, and the bars are the only thing that
 * stretches, which is what a bar is supposed to do.
 *
 * Two bars per row, sharing one scale: share of revenue and share of margin. A
 * negative margin grows leftwards from the same zero, so a loss-maker is a shape
 * rather than a number to notice.
 */
import { computed, ref } from 'vue'

import { formatMoney, formatPercent, formatSku } from '@/core/utils/format'

const props = defineProps({
  categories: { type: Array, required: true },
  currency: { type: String, default: '' },
  /** Cut currently in force — only the article cut carries a seller's code. */
  cut: { type: String, default: 'sku' },
})

/** How many rows before the tail folds. */
const HEAD = 10

const expanded = ref(false)
const hovered = ref(null)
/** Where in the row the pointer is, so the tooltip appears over the cursor. */
const pointer = ref({ x: 0, y: 0 })

const visible = computed(() =>
  expanded.value ? props.categories : props.categories.slice(0, HEAD),
)

const hiddenCount = computed(() => Math.max(0, props.categories.length - HEAD))

/** One scale for both bars, so their lengths are comparable within a row. */
const scale = computed(() => {
  let high = 0
  let low = 0
  for (const row of visible.value) {
    high = Math.max(high, row.revenueShare, row.marginShare ?? 0)
    low = Math.min(low, row.marginShare ?? 0)
  }
  const span = high - low || 1
  return { low, span, zero: (-low / span) * 100 }
})

/** Bar geometry as percentages of the track, measured from the shared zero. */
function bar(share) {
  if (share === null || share === undefined) return null
  const width = (Math.abs(share) / scale.value.span) * 100
  return {
    width: `${Math.max(width, 0.4)}%`,
    left: share < 0 ? `${scale.value.zero - width}%` : `${scale.value.zero}%`,
  }
}

/** A seller's article is printed the way it is on the box — uppercase. */
function label(row) {
  return props.cut === 'sku' ? formatSku(row.label) : row.label
}

const pct = (value) => (value === null || value === undefined ? '—' : formatPercent(value))

/** Follow the pointer inside the hovered row, in the row's own coordinates. */
function track(event) {
  const box = event.currentTarget.getBoundingClientRect()
  pointer.value = { x: event.clientX - box.left, y: event.clientY - box.top }
}
</script>

<template>
  <div class="sum-cat">
    <div class="sum-cat__head">
      <span class="sum-cat__legend">
        <span class="sum-cat__swatch sum-cat__swatch--rev"></span>выручка
        <span class="sum-cat__swatch sum-cat__swatch--mar"></span>маржа
      </span>
      <span class="sum-cat__colhead">выручка</span>
      <span class="sum-cat__colhead">доля в общей</span>
      <span class="sum-cat__colhead">маржа</span>
      <span class="sum-cat__colhead">доля в общей</span>
    </div>

    <div
      v-for="row in visible"
      :key="row.key"
      class="sum-cat__row"
      @pointerenter="hovered = row.key"
      @pointermove="track"
      @pointerleave="hovered = null"
    >
      <div class="sum-cat__label" :title="label(row)">{{ label(row) }}</div>

      <div class="sum-cat__track">
        <span v-if="scale.low < 0" class="sum-cat__zero" :style="{ left: `${scale.zero}%` }"></span>
        <span class="sum-cat__bar sum-cat__bar--rev" :style="bar(row.revenueShare)"></span>
        <span
          v-if="bar(row.marginShare)"
          class="sum-cat__bar sum-cat__bar--mar"
          :class="{ 'sum-cat__bar--neg': row.marginShare < 0 }"
          :style="bar(row.marginShare)"
        ></span>
      </div>

      <div class="sum-cat__num">{{ formatMoney(row.revenue, currency) }}</div>
      <div class="sum-cat__num sum-cat__num--soft">{{ pct(row.revenueShare) }}</div>
      <div class="sum-cat__num" :class="{ 'sum-cat__num--neg': row.margin < 0 }">
        {{ row.margin === null ? '—' : formatMoney(row.margin, currency) }}
      </div>
      <div class="sum-cat__num sum-cat__num--soft">{{ pct(row.marginShare) }}</div>

      <div
        v-if="hovered === row.key"
        class="ui-glass ui-glass--pop sum-cat__tip"
        :style="{ left: `${pointer.x}px`, top: `${pointer.y}px` }"
      >
        <div class="sum-cat__tiprow">
          <span>Продано</span>
          <span class="sum-cat__tipval">{{ row.soldUnits.toLocaleString('ru-RU') }} шт</span>
        </div>
        <div class="sum-cat__tiprow">
          <span>Маржа от выручки</span>
          <span class="sum-cat__tipval">{{ pct(row.marginPct) }}</span>
        </div>
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
