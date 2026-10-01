<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import {
  buildStockRibbon,
  deltaPercent,
  deltaText,
  deltaTone,
} from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 2 — «Терминал».
 *
 * A trading screen's vocabulary, because the question is a trader's one —
 * what moved since yesterday. Near-black ground, monospaced figures, one amber
 * accent for labels, and under every number the day's change in green or red;
 * a cell that moved carries a faint wash of its colour, the way a quote board
 * flashes a tick. Warehouses are three-letter tickers (`warehouseCodes`), the
 * full name a hover away.
 *
 * Hover draws a crosshair: the size across every day and the warehouse down
 * its column, the cell under the pointer outlined.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
})

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.days.some((d) => d.warehouses.length))

function gridColumns(day) {
  const n = day.warehouses.length
  return n ? `var(--total-w) repeat(${n}, minmax(0, 1fr))` : '1fr'
}

/** Only a real move is printed: an unchanged cell stays quiet. */
function moved(delta) {
  return delta ? deltaText(delta) : ''
}

function arrow(delta) {
  return delta > 0 ? '▲' : delta < 0 ? '▼' : ''
}

function percent(day) {
  const p = deltaPercent(day.grandTotal, day.grandDelta)
  if (p === null) return ''
  const sign = p > 0 ? '+' : p < 0 ? '−' : ''
  return `${sign}${Math.abs(p).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
}

function cellTip(day, wh, r) {
  const cell = day.rows[r].cells[wh.name]
  const change = cell.delta ? `  ${deltaText(cell.delta)}` : ''
  return `${wh.code} ${wh.name} · ${ribbon.value.sizes[r].label}  ${formatNumber(cell.q)}${change}`
}
</script>

<template>
  <div class="panel">
    <div v-if="!hasStock" class="empty">НЕТ ДАННЫХ — остатков за период нет</div>

    <StockRibbon
      v-else
      class="term"
      tone="dark"
      :style="{ '--rows': ribbon.sizes.length }"
      :days="ribbon.days"
      :rail-width="86"
      :gap="12"
    >
      <template #lead>
        <div class="status">
          <span class="live"><i />ОСТАТКИ FBO</span>
          <span class="dim">/</span>
          <span>{{ ribbon.days.length }} ДН</span>
          <span class="dim">/</span>
          <span>{{ ribbon.warehouses.length }} СКЛ</span>
          <span class="key"><b class="is-up">▲ ПРИХОД</b><b class="is-down">▼ РАСХОД</b></span>
        </div>
      </template>

      <template #rail="{ hot }">
        <div class="rail">
          <div class="head"><span class="tag">РАЗМЕР</span></div>
          <div class="grid">
            <div class="sub" />
            <div
              v-for="(size, r) in ribbon.sizes"
              :key="size.chrt_id"
              class="r-cell"
              :class="{ 'is-row': hot?.row === r }"
              :title="size.label"
            >
              {{ size.label }}
            </div>
            <div class="foot r-foot">ИТОГ</div>
          </div>
        </div>
      </template>

      <template #day="{ day, hot, point, clear }">
        <section class="day" :aria-label="`${day.label}, всего ${day.grandTotal} шт`">
          <header class="head">
            <div class="when">
              <span>{{ day.weekday.toUpperCase() }}</span>
              <span class="when-date">{{ day.label }}</span>
              <span v-if="day.newest" class="last"><i />ПОСЛЕДНИЙ</span>
            </div>
            <div class="sum">
              <span class="sum-total">{{ formatNumber(day.grandTotal) }}</span>
              <span class="sum-delta" :class="`is-${deltaTone(day.grandDelta)}`">
                {{ arrow(day.grandDelta) }} {{ deltaText(day.grandDelta) }}
                <span class="dim">{{ percent(day) }}</span>
              </span>
            </div>
          </header>

          <div class="grid" :style="{ gridTemplateColumns: gridColumns(day) }">
            <div class="sub sub-total">{{ day.warehouses.length ? 'ИТОГ' : 'НЕТ ОСТАТКОВ' }}</div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="sub"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
              :title="wh.name"
            >
              {{ wh.code }}
            </div>

            <template v-for="(row, r) in day.rows" :key="r">
              <div class="cell total" :class="{ 'is-row': hot?.row === r }">
                <span class="v" :class="{ 'is-empty': !row.total }">
                  {{ row.total ? formatNumber(row.total) : '·' }}
                </span>
                <span class="d" :class="`is-${deltaTone(row.delta)}`">{{ moved(row.delta) }}</span>
              </div>
              <div
                v-for="wh in day.warehouses"
                :key="wh.name"
                class="cell"
                :class="[
                  row.cells[wh.name].delta ? `moved is-${deltaTone(row.cells[wh.name].delta)}` : '',
                  { 'is-row': hot?.row === r, 'is-col': hot?.col === `${day.key}|${wh.name}` },
                ]"
                @mouseenter="
                  point($event, { row: r, col: `${day.key}|${wh.name}`, tip: cellTip(day, wh, r) })
                "
                @mouseleave="clear"
              >
                <span class="v" :class="{ 'is-empty': !row.cells[wh.name].q }">
                  {{ row.cells[wh.name].q ? formatNumber(row.cells[wh.name].q) : '·' }}
                </span>
                <span class="d">{{ moved(row.cells[wh.name].delta) }}</span>
              </div>
            </template>

            <div class="foot cell total">
              <span class="v">{{ formatNumber(day.grandTotal) }}</span>
              <span class="d" :class="`is-${deltaTone(day.grandDelta)}`">
                {{ moved(day.grandDelta) }}
              </span>
            </div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="foot cell"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
            >
              <span class="v">{{ formatNumber(wh.total) }}</span>
              <span class="d" :class="`is-${deltaTone(wh.delta)}`">{{ moved(wh.delta) }}</span>
            </div>
          </div>
        </section>
      </template>
    </StockRibbon>
  </div>
</template>

<style scoped src="./styles/StockTerminalTable.css"></style>
