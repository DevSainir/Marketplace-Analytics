<script setup>
import { computed } from 'vue'

import StockRibbon from '@/modules/labs/components/StockRibbon.vue'
import { buildStockRibbon, deltaText, deltaTone } from '@/modules/labs/stockRibbonModel'

import { formatNumber } from '@/core/utils/format'

/**
 * LAB VARIANT 3 — «Карточки дней».
 *
 * Bento: each day is its own floating card on a tray, with a headline — the
 * day's total, its change, and a segmented bar of how that total splits across
 * warehouses. Inside, every warehouse keeps ONE colour for the whole period
 * (`hue` in the model, by period total — never by its rank on the day), which is
 * what lets the eye follow «Коледино» from card to card although each day lists
 * only the warehouses it stocked and the columns shift.
 *
 * A cell's number sits on a data bar scaled to that warehouse's fullest cell in
 * the period, so a column reads as the warehouse's size curve; a corner tick
 * marks a cell that moved since yesterday.
 */
const props = defineProps({
  /** @type {Array<{stat_date: string, stock: ?object}>} oldest day first. */
  days: { type: Array, default: () => [] },
  /** The union of every day's sizes, so a row lines up across the period. */
  sizeOrder: { type: Array, default: () => [] },
})

const ribbon = computed(() => buildStockRibbon(props.days, props.sizeOrder))
const hasStock = computed(() => ribbon.value.days.some((d) => d.warehouses.length))
const coloured = computed(() => ribbon.value.warehouses.filter((w) => w.hue !== null))
const others = computed(() => ribbon.value.warehouses.length - coloured.value.length)

function hue(wh) {
  return wh.hue === null ? 'var(--wh-other)' : `var(--wh-${wh.hue})`
}

function gridColumns(day) {
  const n = day.warehouses.length
  return n ? `var(--total-w) repeat(${n}, minmax(0, 1fr))` : '1fr'
}

function fill(q, wh) {
  return wh.max ? Math.min(q / wh.max, 1) : 0
}

function arrow(delta) {
  return delta > 0 ? '↑' : delta < 0 ? '↓' : '→'
}

function goneText(gone) {
  const n = gone.length
  if (n === 1) return `опустел ${gone[0]}`
  const few = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)
  return `опустели ${n} ${few ? 'склада' : 'складов'}`
}

function cellTip(day, wh, r) {
  const cell = day.rows[r].cells[wh.name]
  const change = cell.delta ? ` · ${deltaText(cell.delta)} за день` : ''
  return `${wh.name} · ${ribbon.value.sizes[r].label}: ${formatNumber(cell.q)} шт${change}`
}

function mixTip(wh) {
  return `${wh.name}: ${formatNumber(wh.total)} шт · ${Math.round(wh.share * 100)}%`
}
</script>

<template>
  <div class="tray">
    <div v-if="!hasStock" class="py-xl text-center text-base text-muted">
      Нет складских остатков по этому SKU за выбранный период.
    </div>

    <StockRibbon
      v-else
      class="cards"
      :style="{ '--rows': ribbon.sizes.length }"
      :days="ribbon.days"
      :rail-width="74"
      :gap="12"
    >
      <template #lead>
        <ul class="legend" aria-label="Цвета складов">
          <li v-for="wh in coloured" :key="wh.name" :style="{ '--wh': hue(wh) }">
            <i />{{ wh.name }}
          </li>
          <li v-if="others" class="is-other"><i />прочие · {{ others }}</li>
          <li class="is-key"><b class="tick is-up" />приход <b class="tick is-down" />расход</li>
        </ul>
      </template>

      <template #rail="{ hot }">
        <div class="rail">
          <div class="head" />
          <div class="grid">
            <div class="sub r-sub">Размер</div>
            <div v-for="(size, r) in ribbon.sizes" :key="size.chrt_id" class="r-cell">
              <span :class="{ 'is-row': hot?.row === r }" :title="size.label">{{
                size.label
              }}</span>
            </div>
            <div class="foot r-foot">Всего</div>
          </div>
        </div>
      </template>

      <template #day="{ day, hot, point, clear }">
        <section class="card" :aria-label="`${day.label}, всего ${day.grandTotal} шт`">
          <header class="head">
            <div class="top">
              <span class="wd" :class="{ 'is-weekend': day.weekend }">{{ day.weekdayLong }}</span>
              <span class="date">{{ day.dayMonthLong }}</span>
            </div>
            <div class="mid">
              <span class="big tabular-nums">{{ formatNumber(day.grandTotal) }}</span>
              <span class="unit">шт</span>
              <span
                v-if="day.grandDelta !== null"
                class="pill tabular-nums"
                :class="`is-${deltaTone(day.grandDelta)}`"
              >
                {{ arrow(day.grandDelta) }} {{ deltaText(day.grandDelta) }}
              </span>
              <span v-if="day.gone.length" class="gone" :title="day.gone.join(', ')">
                {{ goneText(day.gone) }}
              </span>
            </div>
            <div class="mix">
              <span
                v-for="wh in day.warehouses"
                :key="wh.name"
                class="seg"
                :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
                :style="{ flexGrow: wh.total, '--wh': hue(wh) }"
                @mouseenter="point($event, { col: `${day.key}|${wh.name}`, tip: mixTip(wh) })"
                @mouseleave="clear"
              />
            </div>
          </header>

          <div class="grid" :style="{ gridTemplateColumns: gridColumns(day) }">
            <div class="sub sub-total">{{ day.warehouses.length ? 'Всего' : 'нет остатков' }}</div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="sub sub-wh"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
              :style="{ '--wh': hue(wh) }"
              :title="wh.name"
            >
              <i />{{ wh.code }}
            </div>

            <template v-for="(row, r) in day.rows" :key="r">
              <div class="cell total tabular-nums" :class="{ 'is-row': hot?.row === r }">
                {{ row.total ? formatNumber(row.total) : '' }}
                <b v-if="row.delta" class="tick" :class="`is-${deltaTone(row.delta)}`" />
              </div>
              <div
                v-for="wh in day.warehouses"
                :key="wh.name"
                class="cell tabular-nums"
                :class="{
                  'is-row': hot?.row === r,
                  'is-col': hot?.col === `${day.key}|${wh.name}`,
                  'is-empty': !row.cells[wh.name].q,
                }"
                :style="{ '--wh': hue(wh), '--fill': fill(row.cells[wh.name].q, wh) }"
                @mouseenter="
                  point($event, { row: r, col: `${day.key}|${wh.name}`, tip: cellTip(day, wh, r) })
                "
                @mouseleave="clear"
              >
                <span class="n">
                  {{ row.cells[wh.name].q ? formatNumber(row.cells[wh.name].q) : '' }}
                </span>
                <b
                  v-if="row.cells[wh.name].delta"
                  class="tick"
                  :class="`is-${deltaTone(row.cells[wh.name].delta)}`"
                />
              </div>
            </template>

            <div class="foot foot-total tabular-nums">
              <span>{{ formatNumber(day.grandTotal) }}</span>
            </div>
            <div
              v-for="wh in day.warehouses"
              :key="wh.name"
              class="foot tabular-nums"
              :class="{ 'is-col': hot?.col === `${day.key}|${wh.name}` }"
              :style="{ '--wh': hue(wh) }"
            >
              {{ formatNumber(wh.total) }}
            </div>
          </div>
        </section>
      </template>
    </StockRibbon>
  </div>
</template>

<style scoped src="./styles/StockCardsTable.css"></style>
