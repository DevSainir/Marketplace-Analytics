<script setup>
import { HEAT_LEGEND_TICKS, heatFillAt } from '@/modules/monitoring/stockHeat'

/**
 * The colour key for the stock tables' heatmap: a continuous bar of the ramp
 * with the anchor stops ticked off along it.
 *
 * One legend serves BOTH day tables, which is exactly what the shared global
 * scale buys (see stockHeat.js) — the tint means the same count on either
 * side, so the key belongs next to the section title rather than duplicated
 * over each table.
 *
 * The bar's axis is INTENSITY, not units: each tick sits at its stop's own
 * position on the ramp. So the labels come out unevenly spaced (0 · 1 · 5 ·
 * 12 · 27 · 44 · 80+), which is the honest picture — that uneven spacing IS
 * the quantile-anchored scale, and drawing it any other way would misreport
 * what a given tint means.
 */

/**
 * The bar traces the same piecewise-linear ramp the cells use: one gradient
 * stop per anchor, each at its own place along the bar. It starts at the
 * floor tint rather than at transparent — an empty cell is the faintest thing
 * the table can show, so that IS the left edge.
 */
const barBackground = `linear-gradient(to right, ${HEAT_LEGEND_TICKS.map(
  (tick) => `${heatFillAt(tick.t)} ${(tick.pos * 100).toFixed(1)}%`,
).join(', ')})`
</script>

<template>
  <div
    class="heat-legend"
    role="img"
    aria-label="Шкала остатков: чем насыщеннее цвет, тем больше единиц на складе"
  >
    <span class="text-micro text-muted">шт.</span>
    <div class="heat-legend-scale">
      <div class="heat-legend-bar" :style="{ background: barBackground }"></div>
      <div class="heat-legend-ticks" aria-hidden="true">
        <span
          v-for="(tick, index) in HEAT_LEGEND_TICKS"
          :key="tick.label"
          class="heat-legend-tick"
          :class="{
            'heat-legend-tick--first': index === 0,
            'heat-legend-tick--last': index === HEAT_LEGEND_TICKS.length - 1,
          }"
          :style="{ left: `${tick.pos * 100}%` }"
        >
          {{ tick.label }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.heat-legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.heat-legend-scale {
  width: 190px;
}

/* Hairline border: the floor tint at the low end is nearly invisible by
   design, so without it the bar's left edge would dissolve into the page and
   the key would read as floating labels. */
.heat-legend-bar {
  height: 8px;
  border: 1px solid #e0e0e0;
  border-radius: 2px;
}

/* Ticks hang under the bar, each centred on its own stop. The row needs an
   explicit height because the labels are absolutely positioned out of flow. */
.heat-legend-ticks {
  position: relative;
  height: 12px;
}

.heat-legend-tick {
  position: absolute;
  transform: translateX(-50%);
  color: #858585;
  font-size: 9px;
  line-height: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* The end ticks sit ON the bar's edges, where centring would hang them out
   past it — anchor them inside instead. */
.heat-legend-tick--first {
  transform: none;
}
.heat-legend-tick--last {
  transform: translateX(-100%);
}
</style>
