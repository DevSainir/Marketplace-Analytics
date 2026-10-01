<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import StockWarehouseLegend from '@/modules/labs/components/StockWarehouseLegend.vue'
import {
  buildStockRibbon,
  deltaText,
  deltaTone,
  dotsFor,
  hueVar,
  plural,
  rowTip,
  unitsPerDot,
} from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 2 — «Поштучно».
 *
 * An isotype unit chart: every dot is a unit on the shelf (or a fixed handful
 * of them, `unitsPerDot`, once the fullest size outgrows `MAX_DOTS`). The numbers a seller
 * with one warehouse actually has — tens per size — are small enough to be
 * COUNTED, and a row of 23 dots says «23» in a way a lone figure in a 600px
 * column cannot.
 *
 * What left since yesterday stays in the row as hollow red rings, so a sold
 * unit is a visible gap rather than a smaller number; an arrival rings its new
 * dots green. Several warehouses colour their own runs of dots.
 *
 * Each dot run is ONE element with a repeating radial gradient — a period of
 * twenty sizes × sixty dots × eight days would otherwise be ten thousand nodes.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
})

/** The most dots a row may hold before a dot starts standing for more units. */
const MAX_DOTS = 72

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.maxRow > 0)
const solo = computed(() => ribbon.value.warehouses.length === 1)
const per = computed(() => unitsPerDot(ribbon.value.maxRow, MAX_DOTS))
/**
 * Dots across the row: exactly the fullest size of the period, so that size
 * reaches the end and every dot is as large as the width allows — a fixed
 * capacity left a one-warehouse seller's rows half empty.
 */
const capacity = computed(() => Math.max(1, Math.ceil(ribbon.value.maxRow / per.value)))

/** A run of `n` dots: its width on the row and how many cells it repeats. */
function run(n) {
  return { width: `${(n / capacity.value) * 100}%`, '--n': n }
}

function soldDots(row) {
  return row.prevTotal > row.total ? dotsFor(row.prevTotal - row.total, per.value) : 0
}

/** The filled dots as drawn — a sum of runs, each rounded on its own. */
function filledDots(row) {
  return row.segments.reduce((sum, seg) => sum + dotsFor(seg.q, per.value), 0)
}

function arrivedDots(row) {
  return row.delta > 0 ? Math.min(dotsFor(row.delta, per.value), filledDots(row)) : 0
}

/** The arrival ring sits over the LAST dots of the filled run. */
function arrivalLeft(row) {
  return `${((filledDots(row) - arrivedDots(row)) / capacity.value) * 100}%`
}
</script>

<template>
  <div class="rounded-card bg-surface p-md shadow-card">
    <div v-if="!hasStock" class="py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU за выбранный период.
    </div>

    <StockRibbon v-else class="units" :days="ribbon.days" :rail-width="84" :gap="22">
      <template #lead>
        <StockWarehouseLegend :warehouses="ribbon.warehouses">
          <li class="scale">
            <i class="dot-key" />= {{ per === 1 ? '1 штука' : `${per} шт` }}
            <i class="sold-key" />ушло за день <i class="new-key" />поставка
          </li>
        </StockWarehouseLegend>
      </template>

      <template #rail="{ hot }">
        <div class="rail">
          <div class="head" />
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
            <div>
              <div class="date">{{ day.dayMonthLong }}</div>
              <div class="wd" :class="{ 'is-weekend': day.weekend }">{{ day.weekdayLong }}</div>
            </div>
            <div class="sum">
              <span class="sum-total tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
              <span class="delta-pill tabular-nums" :class="`is-${deltaTone(day.grandDelta)}`">
                {{ deltaText(day.grandDelta) || 'первый день' }}
              </span>
            </div>
          </header>

          <div
            v-for="(row, r) in day.rows"
            :key="r"
            class="row"
            :class="[`is-${row.status}`, { 'is-row': hot?.row === r }]"
            :style="{ '--r': r }"
            @mouseenter="point($event, { row: r, tip: rowTip(ribbon.sizes[r].label, row) })"
            @mouseleave="clear"
          >
            <div class="track">
              <span
                v-for="seg in row.segments"
                :key="seg.name"
                class="dots"
                :style="{ ...run(dotsFor(seg.q, per)), '--dot': hueVar(seg.hue, solo) }"
              />
              <span v-if="soldDots(row)" class="dots is-sold" :style="run(soldDots(row))" />
              <span v-if="!row.total && !soldDots(row)" class="none">нет</span>
              <span
                v-if="arrivedDots(row)"
                class="dots is-new"
                :style="{ ...run(arrivedDots(row)), left: arrivalLeft(row) }"
              />
            </div>
            <span class="qty tabular-nums">{{ row.total ? formatNumber(row.total) : '—' }}</span>
            <span class="delta tabular-nums" :class="`is-${deltaTone(row.delta)}`">
              {{ row.delta ? deltaText(row.delta) : '' }}
            </span>
          </div>

          <div class="row foot">
            <span class="foot-note">
              <b v-if="day.counts.soldOut" class="is-down">
                {{ day.counts.soldOut }}
                {{
                  plural(
                    day.counts.soldOut,
                    'размер закончился',
                    'размера закончились',
                    'размеров закончились',
                  )
                }}
              </b>
              <template v-else>без новых обнулений</template>
            </span>
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

<style scoped src="./styles/StockUnitsTable.css"></style>
