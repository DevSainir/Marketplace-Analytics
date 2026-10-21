<script setup>
/**
 * One row's money by display zone — the breakdown that opens under an article
 * (or a subject, or a brand) in the advertising table.
 *
 * What the zone cards above say for the whole workspace, this says for one row:
 * which kind of campaign took its money and where it was shown. Narrow on
 * purpose — a short list of zones under a wide row, not a second table across
 * it — so it reads as a footnote to the row rather than as a new section.
 *
 * A CSS grid, not a `<table>`: inside `.app-datatable` every `table`, `th` and
 * `td` takes the page table's skin — full width, upper-case padded headers, no
 * wrapping — which stretched this list across the row and set its headings
 * apart from its figures. Fixed column widths keep each heading over its own
 * figures, and two open rows' breakdowns in line with each other.
 */
import { computed } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { ZONE_COLORS, ratioPct } from '@/modules/advertising/adsFormat'
import { skuZoneLines } from '@/modules/advertising/zoneModel'

const props = defineProps({
  /** The row's `zones`: `{zone, spend, bonus}`. */
  zones: { type: Array, required: true },
  /** The row's whole spend, which the zones' shares are of. */
  spend: { type: Number, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
})

const lines = computed(() => skuZoneLines(props.zones, props.spend))
const money = (value) => formatMoney(value, props.currency)
</script>

<template>
  <div class="bg-inset px-md py-sm">
    <p v-if="!lines.length" class="text-tiny text-muted">У этой строки нет рекламы за период.</p>
    <div
      v-else
      class="grid w-max gap-x-lg gap-y-0.5 text-tiny tabular-nums"
      :class="
        showBonus
          ? 'grid-cols-[minmax(12rem,auto)_6.5rem_6.5rem_4rem]'
          : 'grid-cols-[minmax(12rem,auto)_6.5rem_4rem]'
      "
    >
      <span class="text-muted">Зона показа</span>
      <span class="text-right text-muted">Реклама</span>
      <span v-if="showBonus" class="text-right text-muted">Промо-бонусы</span>
      <span class="text-right text-muted">Доля</span>

      <template v-for="line in lines" :key="line.zone">
        <span class="inline-flex items-center gap-xs text-primary">
          <span
            class="inline-block h-2 w-2 flex-none rounded-full"
            :class="line.kind ? '' : 'bg-border-strong/40'"
            :style="line.kind ? { background: ZONE_COLORS[line.kind] } : {}"
          />
          {{ line.label }}
        </span>
        <span class="text-right text-primary">{{ money(line.spend) }}</span>
        <span v-if="showBonus" class="text-right text-muted">{{ money(line.bonus) }}</span>
        <span class="text-right text-muted">{{ ratioPct(line.share) }}</span>
      </template>
    </div>
  </div>
</template>
