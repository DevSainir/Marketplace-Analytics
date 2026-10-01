<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import StockWarehouseLegend from '@/modules/labs/components/StockWarehouseLegend.vue'
import {
  buildStockRibbon,
  deltaText,
  deltaTone,
  hueVar,
  rowTip,
} from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 1 — «Кривая размеров».
 *
 * Each day is a bar chart of its size run: one horizontal bar per size, on a
 * scale shared by the whole period, so scrolling day to day the bars visibly
 * shrink. Yesterday's level is the comparative measure of Stephen Few's
 * bullet graph, drawn the way a prior period is drawn — thin, neutral, dashed —
 * and only where it differs: the stretch a size lost since yesterday is a
 * dashed, red-hatched ghost past the end of its bar; a size that grew carries a
 * dashed tick where it stood and a green outline on what arrived. An unchanged
 * size is a plain bar, so the eye goes straight to the ones that moved.
 *
 * A day of one warehouse fills its width with the size curve instead of with
 * one lonely column; several warehouses become segments of each bar.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
})

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.maxRow > 0)
const solo = computed(() => ribbon.value.warehouses.length === 1)

/** Share of the period's fullest size, as a CSS percentage. */
function pct(units) {
  return `${(Math.max(0, units) / ribbon.value.maxRow) * 100}%`
}

const ticks = computed(() => {
  const max = ribbon.value.maxRow
  return [0, Math.round(max / 2), max]
})
</script>

<template>
  <div class="rounded-card bg-surface p-md shadow-card">
    <div v-if="!hasStock" class="py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU за выбранный период.
    </div>

    <StockRibbon v-else class="curve" :days="ribbon.days" :rail-width="84" :gap="22">
      <template #lead>
        <StockWarehouseLegend :warehouses="ribbon.warehouses">
          <li class="key-note"><i class="sold-key" />ушло за день</li>
          <li class="key-note"><i class="new-key" />поставка</li>
        </StockWarehouseLegend>
      </template>

      <template #rail="{ hot }">
        <div class="rail">
          <div class="head" />
          <div class="axis" />
          <div
            v-for="(size, r) in ribbon.sizes"
            :key="size.chrt_id"
            class="r-cell"
            :class="{ 'is-row': hot?.row === r }"
            :title="size.label"
          >
            {{ size.label }}
          </div>
          <div class="foot r-foot">Всего</div>
        </div>
      </template>

      <template #day="{ day, hot, point, clear }">
        <section class="day" :aria-label="`${day.label}, всего ${day.grandTotal} шт`">
          <header class="head">
            <div class="when">
              <span class="wd" :class="{ 'is-weekend': day.weekend }">{{ day.weekday }}</span>
              <span class="date">{{ day.dayMonthLong }}</span>
            </div>
            <div class="sum">
              <span class="sum-total tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
              <span class="unit">шт</span>
              <span class="delta tabular-nums" :class="`is-${deltaTone(day.grandDelta)}`">
                {{ deltaText(day.grandDelta) }}
              </span>
            </div>
          </header>

          <div class="axis">
            <span v-for="tick in ticks" :key="tick" :style="{ left: pct(tick) }">
              {{ formatNumber(tick) }}
            </span>
          </div>

          <div
            v-for="(row, r) in day.rows"
            :key="r"
            class="row"
            :class="[`is-${row.status}`, { 'is-row': hot?.row === r }]"
            @mouseenter="point($event, { row: r, tip: rowTip(ribbon.sizes[r].label, row) })"
            @mouseleave="clear"
          >
            <div class="track">
              <i
                v-if="row.prevTotal > row.total"
                class="sold"
                :style="{ left: pct(row.total), width: pct(row.prevTotal - row.total) }"
              />
              <span class="bar" :style="{ width: pct(row.total) }">
                <i
                  v-for="seg in row.segments"
                  :key="seg.name"
                  :style="{ flexGrow: seg.q, background: hueVar(seg.hue, solo) }"
                />
              </span>
              <template v-if="row.prevTotal !== null && row.total > row.prevTotal">
                <i
                  class="arrival"
                  :style="{ left: pct(row.prevTotal), width: pct(row.total - row.prevTotal) }"
                />
                <i v-if="row.prevTotal" class="was" :style="{ left: pct(row.prevTotal) }" />
              </template>
              <span v-if="row.status === 'sold-out'" class="flag">закончился</span>
            </div>
            <span class="qty tabular-nums">{{ row.total ? formatNumber(row.total) : '—' }}</span>
            <span class="delta tabular-nums" :class="`is-${deltaTone(row.delta)}`">
              {{ row.delta ? deltaText(row.delta) : '' }}
            </span>
          </div>

          <div class="row foot">
            <div class="track foot-note">
              {{ day.counts.in + day.counts.low }} из {{ day.rows.length }} размеров в наличии
            </div>
            <span class="qty tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
            <span class="delta tabular-nums" :class="`is-${deltaTone(day.grandDelta)}`">
              {{ deltaText(day.grandDelta) }}
            </span>
          </div>
        </section>
      </template>
    </StockRibbon>
  </div>
</template>

<style scoped src="./styles/StockCurveTable.css"></style>
