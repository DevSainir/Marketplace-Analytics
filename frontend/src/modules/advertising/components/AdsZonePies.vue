<script setup>
/**
 * «Зоны показов» — four donuts: all advertising, ручная, единая, CPC — each
 * split into search, shelves and catalogue.
 *
 * Donuts rather than bars because each answers one part-of-a-whole question
 * («куда ушла эта ставка») and the four sit side by side as small multiples.
 * Identity is never colour alone: every slice is labelled with its money and
 * share in the legend under its ring, and the hues are the validated three.
 * Hand-drawn SVG: four arcs each do not need the charting library. A pie with
 * no spend stays in the row as an empty ring, like its zero rows in the table.
 */
import { formatMoney } from '@/core/utils/format'
import { ZONE_COLORS, ratioPct } from '@/modules/advertising/adsFormat'
import { PIE_ZONES } from '@/modules/advertising/zoneModel'

const props = defineProps({
  /** `zonePies`. */
  pies: { type: Array, required: true },
  currency: { type: String, default: '' },
})

const R = 42
const STROKE = 16
const CIRC = 2 * Math.PI * R

/** Dash segments for each slice, with a 2px surface gap between neighbours. */
function arcs(pie) {
  const gap = pie.parts.length > 1 ? 2 : 0
  let offset = 0
  return pie.parts.map((part) => {
    const length = (part.value / pie.total) * CIRC
    const arc = {
      key: part.key,
      color: ZONE_COLORS[part.key],
      dash: `${Math.max(length - gap, 0.5)} ${CIRC}`,
      offset: -offset,
      title: `${part.label}: ${formatMoney(part.value, props.currency)} · ${ratioPct(part.value / pie.total)}`,
    }
    offset += length
    return arc
  })
}
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface p-md shadow-card">
    <div class="flex flex-wrap gap-md text-tiny text-muted">
      <span v-for="zone in PIE_ZONES" :key="zone.key" class="inline-flex items-center gap-xs">
        <span
          class="inline-block h-2.5 w-2.5 rounded-sm"
          :style="{ background: ZONE_COLORS[zone.key] }"
        />
        {{ zone.label }}
      </span>
    </div>
    <div class="mt-md grid grid-cols-2 gap-lg lg:grid-cols-4">
      <figure v-for="pie in pies" :key="pie.key" class="flex flex-col items-center">
        <figcaption class="text-base font-semibold text-primary">{{ pie.label }}</figcaption>
        <div class="text-tiny text-muted">
          <template v-if="pie.total">
            {{ formatMoney(pie.total, currency)
            }}<template v-if="pie.note"> · {{ pie.note }}</template>
          </template>
          <template v-else>нет расхода</template>
        </div>
        <svg
          viewBox="0 0 100 100"
          class="mt-sm h-28 w-28 -rotate-90"
          role="img"
          :aria-label="pie.label"
        >
          <circle
            v-if="!pie.total"
            cx="50"
            cy="50"
            :r="R"
            fill="none"
            class="stroke-border-subtle"
            :stroke-width="STROKE"
          />
          <circle
            v-for="arc in pie.total ? arcs(pie) : []"
            :key="arc.key"
            cx="50"
            cy="50"
            :r="R"
            fill="none"
            :stroke="arc.color"
            :stroke-width="STROKE"
            :stroke-dasharray="arc.dash"
            :stroke-dashoffset="arc.offset"
          >
            <title>{{ arc.title }}</title>
          </circle>
        </svg>
        <ul class="mt-sm w-full max-w-44 text-tiny tabular-nums">
          <li v-for="part in pie.parts" :key="part.key" class="flex justify-between gap-sm">
            <span class="inline-flex items-center gap-xs text-muted">
              <span
                class="inline-block h-2 w-2 rounded-sm"
                :style="{ background: ZONE_COLORS[part.key] }"
              />
              {{ part.label }}
            </span>
            <span class="text-primary">{{ ratioPct(part.value / pie.total) }}</span>
          </li>
        </ul>
      </figure>
    </div>
  </div>
</template>
