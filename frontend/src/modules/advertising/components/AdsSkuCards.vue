<script setup>
/**
 * The per-article list below `sm` — the same rows `AdsSkuTable` renders, one
 * two-line record each.
 *
 * «Реклама» leads with ДРР beside it; share, orders and bonus are the second
 * line. A list has no headers to click, so it carries its own sort, grows ten
 * records at a time, and puts the «Итого» first. «Зоны» under a record opens
 * its money by display zone, as the ▶ does in the desktop table.
 */
import { computed, ref, watch } from 'vue'

import DataState from '@/core/components/DataState.vue'
import AdsSkuZones from '@/modules/advertising/components/AdsSkuZones.vue'
import { formatMoney, formatNumber, formatSku } from '@/core/utils/format'
import { DRR_ALARM, ratioPct } from '@/modules/advertising/adsFormat'

const props = defineProps({
  rows: { type: Array, required: true },
  total: { type: Object, required: true },
  currency: { type: String, default: '' },
  showBonus: { type: Boolean, default: false },
  showDrr: { type: Boolean, default: true },
})

const PAGE = 10

const SORTS = [
  { key: 'spend', label: 'По рекламе' },
  { key: 'drr', label: 'По ДРР от продаж' },
  { key: 'share', label: 'По доле' },
  { key: 'orders', label: 'По заказам' },
]

/** Labels of the records whose zones are open. */
const open = ref(new Set())

function toggle(label) {
  const next = new Set(open.value)
  if (next.has(label)) next.delete(label)
  else next.add(label)
  open.value = next
}

const sortKey = ref('spend')
const shown = ref(PAGE)

// A new filter or grain is a new list — start it from the top again.
watch(
  () => props.rows,
  () => {
    shown.value = PAGE
  },
)

/** Descending; a missing figure sinks to the bottom rather than reading as zero. */
const sorted = computed(() =>
  [...props.rows].sort((a, b) => (b[sortKey.value] ?? -Infinity) - (a[sortKey.value] ?? -Infinity)),
)
const visible = computed(() => sorted.value.slice(0, shown.value))

const money = (value) => formatMoney(value, props.currency)
const drr = (row) => (props.showDrr ? ratioPct(row.drr) : '—')
</script>

<template>
  <div class="rounded-card border border-border-subtle bg-surface px-md py-sm shadow-card">
    <select
      v-model="sortKey"
      aria-label="Сортировка"
      class="mb-sm h-11 w-full rounded-input border border-border-subtle bg-surface px-sm text-base text-primary"
    >
      <option v-for="s in SORTS" :key="s.key" :value="s.key">{{ s.label }}</option>
    </select>

    <div class="flex items-baseline justify-between gap-sm border-b border-border-subtle pb-sm">
      <span class="text-base font-semibold text-primary">Итого {{ rows.length }}</span>
      <span class="font-semibold tabular-nums text-primary">
        {{ money(total.spend) }} · {{ drr(total) }}
      </span>
    </div>

    <DataState v-if="!rows.length" kind="empty" layout="bare" text="Ничего не найдено" />
    <ul class="divide-y divide-border-subtle">
      <li v-for="row in visible" :key="row.label" class="min-h-11 py-sm">
        <div class="flex items-baseline justify-between gap-sm">
          <span class="min-w-0 truncate text-base font-medium text-primary">
            {{ formatSku(row.label) }}<span v-if="row.n" class="text-muted"> · {{ row.n }}</span>
          </span>
          <span class="flex-none font-semibold tabular-nums text-primary">
            {{ money(row.spend) }}
            <span :class="showDrr && row.drr > DRR_ALARM ? 'text-status-negative' : 'text-muted'">
              · {{ drr(row) }}
            </span>
          </span>
        </div>
        <div class="flex justify-between gap-sm text-tiny tabular-nums text-muted">
          <span>
            доля {{ ratioPct(row.share) }} ·
            {{ row.orders === null ? '—' : formatNumber(row.orders) }} заказов
          </span>
          <span v-if="showBonus">бонусы {{ money(row.bonus) }}</span>
        </div>
        <button
          type="button"
          class="mt-xs inline-flex min-h-11 items-center gap-xs text-tiny text-action"
          :aria-expanded="open.has(row.label)"
          @click="toggle(row.label)"
        >
          <span class="inline-block transition" :class="open.has(row.label) && 'rotate-90'">▶</span>
          Зоны показа
        </button>
        <AdsSkuZones
          v-if="open.has(row.label)"
          :zones="row.zones ?? []"
          :spend="row.spend"
          :currency="currency"
          :show-bonus="showBonus"
          class="-mx-md"
        />
      </li>
    </ul>

    <button
      v-if="shown < rows.length"
      type="button"
      class="ui-btn ui-btn--ghost mt-sm min-h-11 w-full"
      @click="shown += PAGE"
    >
      Показать ещё
    </button>
  </div>
</template>
