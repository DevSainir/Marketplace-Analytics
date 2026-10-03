<script setup>
/**
 * «На что ушли» — the window's spend as a tree: payment model, bid type,
 * campaign kind, zone.
 *
 * Built after the tree-grid pattern (AG Grid's hierarchy, Lightning's tree
 * grid): only the first column is indented; a chevron folds a branch; a thin
 * guide per level shows which parent a row hangs from; weight steps down a
 * level at a time. A leaf zone carries a dot in the colour the pies below give
 * it, so the table and the pies read as one figure. «Доля» pairs its number
 * with a bar, so the big branches are found without reading digits.
 *
 * A plain table, not PrimeVue: there is no sorting — the order IS the hierarchy.
 * Below `sm` it keeps its rows but sheds width: the bars and captions go, and
 * the two bonus columns fold into a second line under «Потрачено».
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

/** Step weight down a level at a time; leaves are plain. */
const weight = (row) =>
  row.depth === 0 ? 'font-semibold' : row.group ? 'font-medium' : 'font-body'
const barColor = (row) => (row.kind ? ZONE_COLORS[row.kind] : 'rgb(var(--ui-action-rgb) / 0.55)')
const cell = 'whitespace-nowrap px-sm text-right tabular-nums sm:px-md'
const wide = 'hidden sm:table-cell'
</script>

<template>
  <div class="overflow-x-auto rounded-card border border-border-subtle bg-surface shadow-card">
    <table class="w-full border-collapse text-base">
      <thead>
        <tr
          class="border-b border-border-subtle text-tiny font-medium uppercase tracking-wider text-muted"
        >
          <th class="py-sm pl-sm text-left font-medium sm:pl-md">Тип кампании и зона</th>
          <th class="px-sm py-sm text-right font-medium sm:px-md">Потрачено</th>
          <th class="px-sm py-sm text-right font-medium sm:px-md">
            Доля<span class="hidden sm:inline"> расхода</span>
          </th>
          <template v-if="showBonus">
            <th :class="wide" class="px-md py-sm text-right font-medium">С баланса</th>
            <th :class="wide" class="px-md py-sm text-right font-medium">Промо-бонусы</th>
          </template>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in visible"
          :key="row.id"
          class="h-10 border-b border-border-subtle"
          :class="row.depth === 0 ? 'bg-canvas/70' : 'hover:bg-hover'"
        >
          <td class="py-0 pl-sm pr-sm sm:pl-md sm:pr-md">
            <div class="flex h-10 items-center" :class="weight(row)">
              <span
                v-for="level in row.depth"
                :key="level"
                class="ml-2 mr-2 h-full w-px flex-none bg-border-subtle sm:mr-3"
                aria-hidden="true"
              />
              <button
                v-if="row.group"
                type="button"
                class="mr-xs flex h-6 w-6 flex-none items-center justify-center rounded-btn text-muted transition hover:bg-hover hover:text-primary"
                :aria-expanded="!collapsed.has(row.id)"
                :aria-label="`${collapsed.has(row.id) ? 'Развернуть' : 'Свернуть'}: ${row.label}`"
                @click="toggle(row.id)"
              >
                <svg
                  viewBox="0 0 16 16"
                  class="h-3.5 w-3.5 transition-transform"
                  :class="collapsed.has(row.id) ? '-rotate-90' : ''"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M4 6l4 4 4-4" />
                </svg>
              </button>
              <span
                v-else-if="row.kind"
                class="ml-2 mr-sm h-2 w-2 flex-none rounded-full"
                :style="{ background: ZONE_COLORS[row.kind] }"
                aria-hidden="true"
              />
              <span class="whitespace-nowrap text-primary">{{ row.label }}</span>
              <span
                v-if="row.caption"
                class="ml-sm hidden text-tiny font-body text-muted sm:inline"
              >
                {{ row.caption }}
              </span>
            </div>
          </td>
          <template v-if="row.unknown">
            <td :class="cell" class="text-tiny text-muted">входит в «Полки»</td>
            <td :class="cell" class="text-muted">—</td>
            <template v-if="showBonus">
              <td :class="[cell, wide]" class="text-muted">—</td>
              <td :class="[cell, wide]" class="text-muted">—</td>
            </template>
          </template>
          <template v-else>
            <td :class="[cell, weight(row)]">
              {{ money(row.spend) }}
              <div v-if="showBonus && row.bonus" class="text-micro font-body text-muted sm:hidden">
                бонусы {{ money(row.bonus) }}
              </div>
            </td>
            <td :class="cell">
              <div class="flex items-center justify-end gap-sm">
                <span class="hidden h-1.5 w-24 overflow-hidden rounded-full bg-canvas sm:block">
                  <span
                    class="block h-full rounded-full"
                    :style="{ width: `${(row.share ?? 0) * 100}%`, background: barColor(row) }"
                  />
                </span>
                <span class="text-muted sm:w-16">{{ ratioPct(row.share) }}</span>
              </div>
            </td>
            <template v-if="showBonus">
              <td :class="[cell, wide]">{{ money(row.spend - row.bonus) }}</td>
              <td :class="[cell, wide]" class="text-muted">
                {{ row.bonus ? money(row.bonus) : '—' }}
              </td>
            </template>
          </template>
        </tr>
      </tbody>
      <tfoot>
        <tr class="h-10 font-semibold text-primary">
          <td class="pl-sm sm:pl-md">Итого</td>
          <td :class="cell">
            {{ money(total.spend) }}
            <div v-if="showBonus && total.bonus" class="text-micro font-body text-muted sm:hidden">
              бонусы {{ money(total.bonus) }}
            </div>
          </td>
          <td :class="cell">
            <span class="inline-block sm:w-16">{{ ratioPct(total.spend ? 1 : null) }}</span>
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
