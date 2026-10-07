<script setup>
/**
 * One row's money by display zone — the breakdown that opens under an article
 * (or a subject, or a brand) in the advertising table.
 *
 * What the zone cards above say for the whole кабинет, this says for one row:
 * which kind of campaign took its money and where it was shown. Narrow on
 * purpose — a short list of zones under a wide row, not a second table across
 * it — so it reads as a footnote to the row rather than as a new section.
 *
 * Only the zones the row ran in. A plain `<table>`, as the P&L's size
 * breakdown: it neither sorts nor pages, and a DataTable inside a DataTable row
 * brings a second scroll inside the first.
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
    <table v-else class="text-tiny tabular-nums">
      <thead>
        <tr class="text-muted">
          <th class="py-0.5 pr-lg text-left font-medium">Зона показа</th>
          <th class="py-0.5 pl-md text-right font-medium">Реклама</th>
          <th v-if="showBonus" class="py-0.5 pl-md text-right font-medium">Промо-бонусы</th>
          <th class="py-0.5 pl-md text-right font-medium">Доля</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="line in lines" :key="line.zone">
          <td class="py-0.5 pr-lg text-primary">
            <span class="inline-flex items-center gap-xs">
              <span
                class="inline-block h-2 w-2 flex-none rounded-full"
                :class="line.kind ? '' : 'bg-border-strong/40'"
                :style="line.kind ? { background: ZONE_COLORS[line.kind] } : {}"
              />
              {{ line.label }}
            </span>
          </td>
          <td class="py-0.5 pl-md text-right text-primary">{{ money(line.spend) }}</td>
          <td v-if="showBonus" class="py-0.5 pl-md text-right text-muted">
            {{ money(line.bonus) }}
          </td>
          <td class="py-0.5 pl-md text-right text-muted">{{ ratioPct(line.share) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
