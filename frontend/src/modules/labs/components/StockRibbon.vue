<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useDayPaging } from '@/modules/labs/useDayPaging'
import { useStockRibbonLayout } from '@/modules/labs/useStockRibbonLayout'

import { vDragScroll } from '@/core/utils/dragScroll'

/**
 * The shell the three «Остатки» design variants share: everything about the
 * ribbon that is NOT how it looks.
 *
 * A sticky rail on the left, one block per day, EXACTLY two days on screen —
 * measured by the same `useStockRibbonLayout` the original grid uses, opened on
 * the newest day, and held on a day boundary at rest (`useDayPaging`). Above
 * it, a pager: the two visible dates, arrows, and a dot per day.
 *
 * Flex blocks rather than one `<table>`: two of the variants separate the days
 * with a gap (a glowing seam, a floating card), and a table cannot put space
 * between two column groups. Rows line up across blocks because every variant
 * gives its rail and its days the same fixed row heights.
 *
 * The hovered cell is the shell's too — `hot` ({row, col}) and a tooltip — and
 * every slot receives it, so a variant can light a whole row across all days
 * and the size it belongs to on the rail.
 *
 * Geometry: the rail is `railWidth`, each day is `--group-w`, and `gap` sits
 * after the rail and between days. Two days on screen means
 * `width = rail + 2 × (day + gap)`, so the layout composable is told the rail is
 * `rail + 2 × gap` wide and divides the rest in two.
 */
const props = defineProps({
  /** Model days from `buildStockRibbon` (`key`, `label`, `dayMonth`), oldest first. */
  days: { type: Array, required: true },
  /** Width of the sticky size rail, px. */
  railWidth: { type: Number, required: true },
  /** Space after the rail and between days, px. */
  gap: { type: Number, default: 0 },
  /** The tooltip's palette — it is teleported, so it cannot inherit the variant's. */
  tone: { type: String, default: 'light' },
})

const PER_SCREEN = 2
/** Past a month a dot per day stops being a pager; the arrows and dates stay. */
const MAX_DOTS = 31

const { root, scroll, groupWidth } = useStockRibbonLayout({ daysSource: () => props.days })
/**
 * Whole pixels. A fractional day makes every scroll position fractional too,
 * and the sticky rail then rounds one way while the days round the other — a
 * half-pixel sliver of the day underneath shows along the rail's edge. The
 * floor costs at most a pixel of slack at the right.
 */
const dayWidth = computed(() => (groupWidth.value ? Math.floor(groupWidth.value) : null))
const { first, offset, go } = useDayPaging({
  scroll,
  step: () => (dayWidth.value ?? 0) + props.gap,
  count: () => props.days.length,
  perScreen: PER_SCREEN,
})

const rootStyle = computed(() => ({
  '--rail-w': `${props.railWidth}px`,
  '--gap': `${props.gap}px`,
  '--col-size-w': `${props.railWidth + PER_SCREEN * props.gap}px`,
  ...(dayWidth.value ? { '--group-w': `${dayWidth.value}px` } : {}),
}))

const range = computed(() => {
  const a = props.days[first.value]
  const b = props.days[first.value + 1]
  return b ? `${a.dayMonth} — ${b.dayMonth}` : (a?.dayMonth ?? '')
})

const hot = ref(null)
const tip = ref(null)

/** Light up a cell's row and column; `tip` adds a tooltip over it. */
function point(event, { row = null, col = null, tip: text = null } = {}) {
  hot.value = { row, col }
  if (!text) {
    tip.value = null
    return
  }
  const rect = event.currentTarget.getBoundingClientRect()
  tip.value = { text, x: rect.left + rect.width / 2, y: rect.top }
}

function clear() {
  hot.value = null
  tip.value = null
}

// The tooltip is `fixed`: any scroll — the ribbon's or the page's — strands it.
onMounted(() => document.addEventListener('scroll', clear, true))
onBeforeUnmount(() => document.removeEventListener('scroll', clear, true))
</script>

<template>
  <div ref="root" class="ribbon" :class="{ 'is-scrolled': offset > 1 }" :style="rootStyle">
    <div class="ribbon-bar">
      <div class="ribbon-lead"><slot name="lead" /></div>
      <nav class="ribbon-pager" aria-label="Дни периода">
        <span class="ribbon-range tabular-nums">{{ range }}</span>
        <button
          type="button"
          class="ribbon-arrow"
          :disabled="first <= 0"
          aria-label="Раньше"
          @click="go(first - 1)"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>
        </button>
        <template v-if="days.length <= MAX_DOTS">
          <button
            v-for="(day, i) in days"
            :key="day.key"
            type="button"
            class="ribbon-dot"
            :class="{ 'is-on': i === first || i === first + 1 }"
            :aria-label="day.label"
            :aria-current="i === first ? 'true' : undefined"
            @click="go(i)"
          />
        </template>
        <button
          type="button"
          class="ribbon-arrow"
          :disabled="first >= days.length - PER_SCREEN"
          aria-label="Позже"
          @click="go(first + 1)"
        >
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
        </button>
      </nav>
    </div>

    <div ref="scroll" v-drag-scroll class="ribbon-scroll" @mouseleave="clear">
      <div class="ribbon-track">
        <div class="ribbon-rail">
          <slot name="rail" :hot="hot" :point="point" :clear="clear" />
        </div>
        <div v-for="(day, i) in days" :key="day.key" class="ribbon-day">
          <slot name="day" :day="day" :index="i" :hot="hot" :point="point" :clear="clear" />
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="tip"
        class="ribbon-tip"
        :class="`is-${tone}`"
        :style="{ left: `${tip.x}px`, top: `${tip.y}px` }"
      >
        {{ tip.text }}
      </div>
    </Teleport>
  </div>
</template>

<style scoped src="./styles/StockRibbon.css"></style>
