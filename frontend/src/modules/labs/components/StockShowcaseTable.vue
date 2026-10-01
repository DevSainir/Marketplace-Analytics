<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import StockWarehouseLegend from '@/modules/labs/components/StockWarehouseLegend.vue'
import {
  LOW_STOCK,
  buildStockRibbon,
  deltaText,
  deltaTone,
  hueVar,
  plural,
  rowTip,
} from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 3 — «Витрина размеров».
 *
 * The day as the buyer meets it: the size picker of a product page, one chip
 * per size, in the conventions shoppers already read without a legend —
 * a hatched, struck-through chip is out of stock (Baymard's exposed size
 * buttons; the to-scale size guides that hatch a missing size), an amber one
 * is running out, a red-ringed one sold out since yesterday, a green flag is a
 * delivery. The question it answers first is the one that costs orders: which
 * sizes can be bought today.
 *
 * Chips flow in a grid of the same width every day, so a size sits in the
 * same place on both days and the eye compares by position. No rail: the size
 * is printed on its chip.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a chip keeps its place across days. */
  sizeOrder: { type: Array, default: () => [] },
})

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.maxRow > 0)
const solo = computed(() => ribbon.value.warehouses.length === 1)

/** A run on the chip's meter: its share of this size's best day in the period. */
function meter(units, r) {
  const peak = ribbon.value.sizePeaks[r]
  return peak ? `${(units / peak) * 100}%` : '0%'
}
</script>

<template>
  <div class="rounded-card bg-surface p-md shadow-card">
    <div v-if="!hasStock" class="py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU за выбранный период.
    </div>

    <StockRibbon v-else class="showcase" :days="ribbon.days" :rail-width="0" :gap="28">
      <template #lead>
        <StockWarehouseLegend :warehouses="ribbon.warehouses">
          <li class="note">
            <i class="is-in" />есть <i class="is-low" />мало, ≤ {{ LOW_STOCK }} шт
            <i class="is-sold-out" />закончился <i class="is-out" />нет
          </li>
        </StockWarehouseLegend>
      </template>

      <template #day="{ day, hot, point, clear }">
        <section class="day" :aria-label="`${day.label}, всего ${day.grandTotal} шт`">
          <header class="head">
            <div class="head-top">
              <div>
                <span class="date">{{ day.dayMonthLong }}</span>
                <span class="wd" :class="{ 'is-weekend': day.weekend }">
                  {{ day.weekdayLong }}
                </span>
              </div>
              <div class="sum">
                <span class="sum-total tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
                <span class="unit">шт</span>
                <span
                  v-if="day.grandDelta !== null"
                  class="delta-pill tabular-nums"
                  :class="`is-${deltaTone(day.grandDelta)}`"
                >
                  {{ deltaText(day.grandDelta) }}
                </span>
              </div>
            </div>
            <div class="counts">
              <span class="is-in">{{ day.counts.in }} в наличии</span>
              <span v-if="day.counts.low" class="is-low">{{ day.counts.low }} мало</span>
              <span v-if="day.counts.soldOut" class="is-sold-out">
                {{ day.counts.soldOut }}
                {{ plural(day.counts.soldOut, 'закончился', 'закончились', 'закончились') }}
              </span>
              <span v-if="day.counts.out" class="is-out">{{ day.counts.out }} нет</span>
            </div>
          </header>

          <ul class="chips">
            <li
              v-for="(row, r) in day.rows"
              :key="r"
              class="chip"
              :class="[`is-${row.status}`, { 'is-row': hot?.row === r }]"
              @mouseenter="point($event, { row: r, tip: rowTip(ribbon.sizes[r].label, row) })"
              @mouseleave="clear"
            >
              <div class="chip-top">
                <span class="chip-size">{{ ribbon.sizes[r].label }}</span>
                <span
                  v-if="row.delta"
                  class="chip-delta tabular-nums"
                  :class="`is-${deltaTone(row.delta)}`"
                >
                  {{ deltaText(row.delta) }}
                </span>
              </div>
              <div class="chip-qty tabular-nums">
                <template v-if="row.total">
                  <b>{{ formatNumber(row.total) }}</b> шт
                </template>
                <template v-else-if="row.status === 'sold-out'">закончился</template>
                <template v-else>нет в наличии</template>
              </div>
              <div class="chip-meter">
                <i
                  v-for="seg in row.segments"
                  :key="seg.name"
                  :style="{ width: meter(seg.q, r), background: hueVar(seg.hue, solo) }"
                />
                <b
                  v-if="row.prevTotal !== null && row.prevTotal !== row.total"
                  class="chip-mark"
                  :style="{ left: meter(row.prevTotal, r) }"
                />
              </div>
              <span v-if="row.delta > 0" class="chip-flag is-up">поставка</span>
            </li>
          </ul>
        </section>
      </template>
    </StockRibbon>
  </div>
</template>

<style scoped src="./styles/StockShowcaseTable.css"></style>
