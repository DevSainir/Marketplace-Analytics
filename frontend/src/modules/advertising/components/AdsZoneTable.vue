<script setup>
/**
 * «На что ушли» — the window's spend as a tree: payment model, bid type,
 * campaign kind, zone.
 *
 * Built after the tree-grid pattern (AG Grid's hierarchy, Lightning's tree
 * grid): only the first column is indented, a chevron folds a branch, weight
 * steps down a level at a time. Indentation alone carries the nesting — guide
 * lines were tried and read as clutter. A leaf zone carries a dot in the
 * colour the pies below give it, and the chevron and the dot share one slot,
 * so a child's label starts exactly one step right of its parent's.
 *
 * Dense on purpose: 28px rows in the small type, because the table is a map
 * of every way WB bills advertising and shows every branch, idle ones
 * included — at zero, muted — so it has to stay short enough to take in at
 * once. Below `sm` the bars and captions go and the two bonus columns fold
 * into a second line under «Потрачено».
 *
 * A plain table, not PrimeVue: there is no sorting — the order IS the hierarchy.
 */
import { computed, ref } from 'vue'

import { formatMoney } from '@/core/utils/format'
import { ZONE_COLORS, ratioPct } from '@/modules/advertising/adsFormat'

const props = defineProps({
  /** `zoneRows` — depth-first, groups before their children. */
  rows: { type: Array, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
})

const money = (value) => formatMoney(value, props.currency)

const collapsed = ref(new Set())
const visible = computed(() =>
  props.rows.filter((row) => !row.ancestors.some((id) => collapsed.value.has(id))),
)
function toggle(id) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
}

const total = computed(() =>
  props.rows
    .filter((row) => row.depth === 0)
    .reduce((acc, row) => ({ spend: acc.spend + row.spend, bonus: acc.bonus + row.bonus }), {
      spend: 0,
      bonus: 0,
    }),
)

/** 16px per level, after the 12px the first column starts at. */
const indent = (depth) => ({ paddingLeft: `${12 + depth * 16}px` })
const weight = (row) => (row.depth === 0 ? 'font-semibold' : row.group ? 'font-medium' : '')
const barColor = (row) => (row.kind ? ZONE_COLORS[row.kind] : 'rgb(var(--ui-action-rgb) / 0.5)')
const cell = 'whitespace-nowrap px-sm py-1 text-right tabular-nums sm:px-md'
const wide = 'hidden sm:table-cell'
</script>

<template>
  <div class="overflow-x-auto rounded-card border border-border-subtle bg-surface shadow-card">
    <table class="w-full border-collapse text-tiny leading-none">
      <thead>
        <tr
          class="h-7 border-b border-border-subtle text-micro font-medium uppercase tracking-wider text-muted"
        >
          <th class="pl-sm text-left font-medium sm:pl-md">Тип кампании и зона</th>
          <th :class="cell" class="font-medium">Потрачено</th>
          <th :class="cell" class="font-medium">
            Доля<span class="hidden sm:inline"> расхода</span>
          </th>
          <template v-if="showBonus">
            <th :class="[cell, wide]" class="font-medium">С баланса</th>
            <th :class="[cell, wide]" class="font-medium">Промо-бонусы</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in visible"
          :key="row.id"
          class="h-7 border-b border-border-subtle"
          :class="row.depth === 0 ? 'bg-canvas/70' : 'hover:bg-hover'"
        >
          <td class="py-1 pr-sm" :style="indent(row.depth)">
            <div class="flex items-center" :class="weight(row)">
              <span class="mr-xs flex h-4 w-4 flex-none items-center justify-center">
                <button
                  v-if="row.group"
                  type="button"
                  class="flex h-4 w-4 items-center justify-center rounded-sm text-muted transition hover:bg-hover hover:text-primary"
                  :aria-expanded="!collapsed.has(row.id)"
                  :aria-label="`${collapsed.has(row.id) ? 'Развернуть' : 'Свернуть'}: ${row.label}`"
                  @click="toggle(row.id)"
                >
                  <svg
                    viewBox="0 0 16 16"
                    class="h-3 w-3 transition-transform"
                    :class="collapsed.has(row.id) ? '-rotate-90' : ''"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M4 6l4 4 4-4" />
                  </svg>
                </button>
                <span
                  v-else-if="row.kind"
                  class="h-1.5 w-1.5 rounded-full"
                  :style="{ background: ZONE_COLORS[row.kind] }"
                  aria-hidden="true"
                />
              </span>
              <span class="whitespace-nowrap" :class="row.spend ? 'text-primary' : 'text-muted'">
                {{ row.label }}
              </span>
              <span v-if="row.caption" class="ml-sm hidden font-body text-muted sm:inline">
                {{ row.caption }}
              </span>
            </div>
          </td>

          <td :class="[cell, weight(row), row.spend ? '' : 'text-muted']">
            {{ money(row.spend) }}
            <div
              v-if="showBonus && row.bonus"
              class="mt-0.5 text-micro font-body text-muted sm:hidden"
            >
              бонусы {{ money(row.bonus) }}
            </div>
          </td>
          <td :class="cell">
            <div class="flex items-center justify-end gap-sm">
              <span class="hidden h-1 w-16 overflow-hidden rounded-full bg-canvas sm:block">
                <span
                  class="block h-full rounded-full"
                  :style="{ width: `${(row.share ?? 0) * 100}%`, background: barColor(row) }"
                />
              </span>
              <span class="text-muted sm:w-14">{{ ratioPct(row.share) }}</span>
            </div>
          </td>
          <template v-if="showBonus">
            <td :class="[cell, wide, row.spend ? '' : 'text-muted']">
              {{ money(row.spend - row.bonus) }}
            </td>
            <td :class="[cell, wide]" class="text-muted">
              {{ row.bonus ? money(row.bonus) : '—' }}
            </td>
          </template>
        </tr>
      </tbody>
      <tfoot>
        <tr class="h-7 font-semibold text-primary">
          <td class="pl-sm sm:pl-md">Итого</td>
          <td :class="cell">
            {{ money(total.spend) }}
            <div
              v-if="showBonus && total.bonus"
              class="mt-0.5 text-micro font-body text-muted sm:hidden"
            >
              бонусы {{ money(total.bonus) }}
            </div>
          </td>
          <td :class="cell">
            <span class="inline-block sm:w-14">{{ ratioPct(total.spend ? 1 : null) }}</span>
          </td>
          <template v-if="showBonus">
            <td :class="[cell, wide]">{{ money(total.spend - total.bonus) }}</td>
            <td :class="[cell, wide]">{{ money(total.bonus) }}</td>
          </template>
        </tr>
      </tfoot>
    </table>
  </div>
</template>
