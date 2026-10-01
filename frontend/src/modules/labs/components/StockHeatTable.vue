<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import {
  HEAT_STEPS,
  buildStockRibbon,
  deltaText,
  deltaTone,
  heatLevel,
} from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 1 — «Теплокарта».
 *
 * Datawrapper's heatmap tables and GitHub's contribution grid, crossed: every
 * size × warehouse figure is a rounded tile whose colour IS the quantity, on a
 * one-hue violet ramp (square-root steps — see `heatLevel`). The eye finds the
 * piles and the holes before it reads a single digit; the digits stay for
 * whoever needs the number.
 *
 * Warehouse names stand upright, Datawrapper-style, so a 40px column carries
 * «Электросталь» whole instead of «Электрос…».
 *
 * Hover is focus + context: the hovered size across every day and the hovered
 * warehouse column stay lit, everything else steps back.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
})

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.days.some((d) => d.warehouses.length))

function heat(q) {
  return heatLevel(q, ribbon.value.maxCell)
}

/** `--n` warehouse columns after «Всего»; a day that held nothing is «Всего» alone. */
function gridColumns(day) {
  const n = day.warehouses.length
  return n ? `var(--total-w) repeat(${n}, minmax(0, 1fr))` : '1fr'
}

function cellTip(day, wh, r) {
  const cell = day.rows[r].cells[wh.name]
  const delta = deltaText(cell.delta)
  const change = delta && delta !== '0' ? ` · ${delta} за день` : ''
  return `${wh.name} · ${ribbon.value.sizes[r].label}: ${formatNumber(cell.q)} шт${change}`
}
</script>

<template>
  <div class="rounded-card bg-surface p-md shadow-card">
    <div v-if="!hasStock" class="py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU за выбранный период.
    </div>

    <StockRibbon
      v-else
      class="heat"
      :style="{ '--rows': ribbon.sizes.length }"
      :days="ribbon.days"
      :rail-width="72"
      :gap="14"
    >
      <template #lead>
        <div class="legend" aria-label="Шкала: сколько штук в ячейке">
          <span>мало</span>
          <i v-for="level in HEAT_STEPS" :key="level" :class="`h${level}`" />
          <span>много</span>
        </div>
      </template>

      <template #rail="{ hot }">
        <div class="rail" :class="{ 'has-hot': hot }">
          <div class="head" />
          <div class="grid">
            <div class="sub r-sub">Размер</div>
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
        </div>
      </template>

      <template #day="{ day, hot, point, clear }">
        <section
          class="day"
          :class="{ 'has-hot': hot }"
          :aria-label="`${day.label}, всего ${day.grandTotal} шт`"
        >
          <header class="head">
            <div class="when">
              <span class="wd" :class="{ 'is-weekend': day.weekend }">{{ day.weekday }}</span>
              <span class="date">{{ day.dayMonthLong }}</span>
            </div>
            <div class="sum">
              <span class="sum-total tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
              <span class="delta tabular-nums" :class="`is-${deltaTone(day.grandDelta)}`">
                {{ deltaText(day.grandDelta) }}
              </span>
            </div>
          </header>

          <div class="grid" :style="{ gridTemplateColumns: gridColumns(day) }">
            <div class="sub sub-total">{{ day.warehouses.length ? 'Всего' : 'нет остатков' }}</div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="sub sub-wh"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
              :title="wh.name"
            >
              <span>{{ wh.name }}</span>
            </div>

            <template v-for="(row, r) in day.rows" :key="r">
              <div
                class="total tabular-nums"
                :class="{ 'is-row': hot?.row === r }"
                :style="{ '--share': day.peak ? row.total / day.peak : 0 }"
              >
                {{ row.total ? formatNumber(row.total) : '' }}
              </div>
              <div
                v-for="wh in day.warehouses"
                :key="wh.name"
                class="tile tabular-nums"
                :class="[
                  `h${heat(row.cells[wh.name].q)}`,
                  { 'is-row': hot?.row === r, 'is-col': hot?.col === `${day.key}|${wh.name}` },
                ]"
                @mouseenter="
                  point($event, { row: r, col: `${day.key}|${wh.name}`, tip: cellTip(day, wh, r) })
                "
                @mouseleave="clear"
              >
                {{ row.cells[wh.name].q ? formatNumber(row.cells[wh.name].q) : '' }}
              </div>
            </template>

            <div class="foot foot-total tabular-nums">{{ formatNumber(day.grandTotal) }}</div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="foot tabular-nums"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
            >
              {{ formatNumber(wh.total) }}
            </div>
          </div>
        </section>
      </template>
    </StockRibbon>
  </div>
</template>

<style scoped src="./styles/StockHeatTable.css"></style>
