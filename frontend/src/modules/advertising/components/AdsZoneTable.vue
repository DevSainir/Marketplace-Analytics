<script setup>
/**
 * «На что ушли» — the window's spend as a tree: payment model, bid type,
 * campaign kind, zone.
 *
 * Indented like nested code, so a row's parent is read off its left edge
 * rather than from a column. A plain table, not PrimeVue: it has no sorting
 * (the order IS the hierarchy) and it is a dozen rows. Compact type, because it
 * shares the overview with the cards; on a phone it takes the full width and
 * keeps its columns — three or five narrow ones fit.
 */
import { formatMoney } from '@/core/utils/format'
import { ratioPct } from '@/modules/advertising/adsFormat'

const props = defineProps({
  /** `zoneRows` — depth-first, groups before their children. */
  rows: { type: Array, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
})

const money = (value) => formatMoney(value, props.currency)
/** 12px per level: enough to read the nesting, little enough for four levels. */
const indent = (depth) => ({ paddingLeft: `${12 + depth * 12}px` })
</script>

<template>
  <div
    class="h-full overflow-x-auto rounded-card border border-border-subtle bg-surface shadow-card"
  >
    <table class="w-full border-collapse text-tiny">
      <thead>
        <tr class="border-b border-border-subtle text-micro uppercase tracking-wider text-muted">
          <th class="py-sm pl-sm text-left font-medium">Тип</th>
          <th class="px-sm py-sm text-right font-medium">Потрачено</th>
          <th class="px-sm py-sm text-right font-medium">Доля</th>
          <template v-if="showBonus">
            <th class="px-sm py-sm text-right font-medium">С баланса</th>
            <th class="py-sm pl-sm pr-md text-right font-medium">Бонусы</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="`${row.depth}-${row.key}`"
          class="border-b border-border-subtle last:border-b-0"
          :class="row.depth === 0 ? 'bg-canvas' : ''"
        >
          <td
            class="whitespace-nowrap py-xs pr-sm"
            :class="row.group ? 'font-semibold text-primary' : 'text-primary'"
            :style="indent(row.depth)"
          >
            {{ row.label }}
            <span v-if="row.hint" class="ml-xs cursor-help text-muted" :title="row.hint">ⓘ</span>
          </td>
          <template v-if="row.unknown">
            <td class="px-sm py-xs text-right text-muted" :title="row.hint">нет данных</td>
            <td class="px-sm py-xs text-right text-muted">—</td>
            <template v-if="showBonus">
              <td class="px-sm py-xs text-right text-muted">—</td>
              <td class="py-xs pl-sm pr-md text-right text-muted">—</td>
            </template>
          </template>
          <template v-else>
            <td
              class="whitespace-nowrap px-sm py-xs text-right tabular-nums"
              :class="row.group ? 'font-semibold' : ''"
            >
              {{ money(row.spend) }}
            </td>
            <td class="px-sm py-xs text-right tabular-nums text-muted">
              {{ ratioPct(row.share) }}
            </td>
            <template v-if="showBonus">
              <td class="whitespace-nowrap px-sm py-xs text-right tabular-nums">
                {{ money(row.spend - row.bonus) }}
              </td>
              <td
                class="whitespace-nowrap py-xs pl-sm pr-md text-right tabular-nums"
                :class="row.bonus ? '' : 'text-muted'"
              >
                {{ row.bonus ? money(row.bonus) : '—' }}
              </td>
            </template>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
</template>
