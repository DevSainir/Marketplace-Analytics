<script setup>
/**
 * The stock balance as cards — the phone projection of `BalanceTable`.
 *
 * The desktop shape is a SKU × warehouse grid with three total panels tracking
 * its scroll. None of that survives a 402pt screen: with a dozen warehouses the
 * cells land a few pixels wide, and the panels exist precisely to keep totals
 * beside a grid that is scrolling in two directions.
 *
 * A phone reads one SKU at a time, so each becomes a card carrying the figures
 * that make this a balance rather than a stock list — the units lying there,
 * the units in transit, and what they cost to put there — with the per-warehouse
 * split folded away. «Итого» leads the list, because on a phone it would
 * otherwise be a scroll away past every SKU.
 *
 * Fed the same rows and totals as the grid (`useBalanceRows`), so the shared
 * toolbar's search and filters apply to both. Marking a warehouse «не считать»
 * is a desktop affordance (it lives in a right-click menu over a column header)
 * and stays there; the cards show the marks' effect, honouring the same totals.
 */
import { computed, ref, watch } from 'vue'

import { formatNumber } from '@/core/utils/format'

const props = defineProps({
  /** @type {Array<object>} Rows from `useBalanceRows`, already filtered/ordered. */
  rows: { type: Array, default: () => [] },
  /** @type {Array<{name, isPinned, isUncounted}>} Warehouse columns, in order. */
  columns: { type: Array, default: () => [] },
  /** @type {{quantity: number, inWay: number, balance: number|null}} The corner total. */
  totals: { type: Object, default: () => ({ quantity: 0, inWay: 0, balance: null }) },
  /** Currency formatter from `moneyFormatter`. */
  money: { type: Function, required: true },
})

const PAGE = 10
const shown = ref(PAGE)
watch(
  () => props.rows,
  () => {
    shown.value = PAGE
  },
)

const visible = computed(() => props.rows.slice(0, shown.value))

const expanded = ref(new Set())

function toggle(nmId) {
  const next = new Set(expanded.value)
  if (!next.delete(nmId)) next.add(nmId)
  expanded.value = next
}

/** The warehouses this SKU actually sits in, in the grid's column order. */
function stocked(row) {
  return props.columns
    .map((column) => ({ ...column, cell: row.byWarehouse[column.name] }))
    .filter((column) => column.cell)
}
</script>

<template>
  <div class="p-md">
    <!-- «Итого» first: the corner block of the desktop grid, which a phone would
         otherwise only reach after scrolling every SKU. -->
    <div
      class="flex items-center justify-between gap-sm rounded-input border border-action/30 bg-action/10 px-md py-sm"
    >
      <span class="text-tiny font-medium uppercase tracking-wider text-muted">Итого</span>
      <span class="text-right">
        <span class="block text-base font-bold tabular-nums text-primary">
          {{ formatNumber(totals.quantity) }} шт
          <span v-if="totals.inWay" class="text-tiny font-medium text-muted">
            +{{ formatNumber(totals.inWay) }} в пути
          </span>
        </span>
        <span class="block text-tiny tabular-nums text-muted">{{ money(totals.balance) }}</span>
      </span>
    </div>

    <ul class="record-list mt-md">
      <li v-for="row in visible" :key="row.nmId" class="record-card">
        <button
          type="button"
          class="record-summary"
          :aria-expanded="expanded.has(row.nmId)"
          @click="toggle(row.nmId)"
        >
          <span class="record-main">
            <span class="record-title" :class="row.isUncounted && 'text-muted line-through'">
              {{ row.saName }}
              <span v-if="row.isPinned" class="text-tiny font-semibold text-action">★</span>
            </span>
            <span class="record-sub">
              {{ row.nmId }}
              <template v-if="row.subject"> · {{ row.subject }}</template>
            </span>
          </span>

          <span class="record-figures">
            <span class="record-value">
              {{ formatNumber(row.totalQuantity) }} шт
              <span v-if="row.totalInWay" class="text-tiny font-normal text-muted">
                +{{ formatNumber(row.totalInWay) }} в пути
              </span>
            </span>
            <!-- `null` is «нет себестоимости», which is not the same statement as
                 a zero balance — the grid draws the same distinction. -->
            <span class="record-support">
              {{ row.totalBalance === null ? '—' : money(row.totalBalance) }} ·
              {{ stocked(row).length }} скл.
            </span>
          </span>

          <svg
            class="record-chevron"
            :class="expanded.has(row.nmId) && 'record-chevron--open'"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>

        <div v-if="expanded.has(row.nmId)" class="record-details">
          <div v-for="column in stocked(row)" :key="column.name" class="record-row">
            <span class="record-label" :class="column.isUncounted && 'line-through'">
              {{ column.name }}
            </span>
            <span class="record-value">
              {{ formatNumber(column.cell.quantity) }} шт
              <span v-if="column.cell.inWay" class="text-muted">
                (+{{ formatNumber(column.cell.inWay) }} в пути)
              </span>
              <span v-if="column.cell.balance !== null" class="text-muted">
                · {{ money(column.cell.balance) }}
              </span>
            </span>
          </div>
        </div>
      </li>
    </ul>

    <button
      v-if="shown < rows.length"
      type="button"
      class="mt-sm min-h-11 w-full rounded-btn border border-border-subtle bg-surface text-base font-medium text-primary transition hover:border-action hover:text-action"
      @click="shown += PAGE"
    >
      Показать ещё ({{ rows.length - shown }})
    </button>
  </div>
</template>

<style scoped src="./styles/RecordCards.css"></style>
