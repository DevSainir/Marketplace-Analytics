<script setup>
/**
 * The per-SKU P&L as cards — the phone projection of `PnlSkuTable`.
 *
 * Eighteen money columns per SKU cannot be narrowed into a 402pt screen, and a
 * sideways-scrolling table hides the two columns anyone opens this page for
 * («Чистая прибыль» and «Продажи») behind four swipes. So each SKU becomes a
 * two-line ROW — the card photo, identity and profit on the first, the margin
 * and the revenue behind it on the second — with the other fifteen columns
 * behind the row.
 *
 * A row rather than a padded card on purpose: with card chrome per SKU the list
 * ran to one screen every two records, which is not a report anyone scrolls.
 *
 * Fed the SAME `tableRows` the table renders — one report, two projections, so
 * the search and the Тип предмета / Бренд filters in the shared toolbar apply to
 * both without being wired twice. Sorting is this component's own: the table
 * sorts by clicking a header, and there are no headers here.
 *
 * Every figure arrives computed from the backend (see docs/finreports/PNL.md);
 * this only formats and orders.
 */
import { computed, ref, watch } from 'vue'

import SkuThumb from '@/core/components/SkuThumb.vue'
import PnlSkuCardsTotals from '@/modules/finreports/components/PnlSkuCardsTotals.vue'
import { DETAILS, SORT_KEYS, money, pct } from '@/modules/finreports/pnlCardColumns'
import { toneClass } from '@/modules/finreports/pnlThresholds'

const props = defineProps({
  /** @type {Array<object>} Flattened rows from `usePnlSkuRows`, already filtered. */
  rows: { type: Array, default: () => [] },
  /** @type {object|null} The «Итого» row from `sumRows`, pinned under the list. */
  totals: { type: Object, default: null },
  currency: { type: String, default: '' },
})

const emit = defineEmits(['toggle-exclusion'])

const sortKey = ref('profit')
const descending = ref(true)

/** How many cards are rendered; «Показать ещё» grows it. A paginator would
 *  make the seller jump pages to find the next loss-maker. */
const PAGE = 10
const shown = ref(PAGE)
watch(
  () => [props.rows, sortKey.value, descending.value],
  () => {
    shown.value = PAGE
  },
)

const sorted = computed(() => {
  const key = sortKey.value
  const direction = descending.value ? -1 : 1
  return [...props.rows].sort((a, b) => {
    // The account-level bucket is not a SKU and always trails, whatever the sort.
    if (a.isBucket !== b.isBucket) return a.isBucket ? 1 : -1
    const x = a[key]
    const y = b[key]
    if (typeof x === 'string' || typeof y === 'string') {
      return direction * String(x ?? '').localeCompare(String(y ?? ''), 'ru')
    }
    // A missing figure is not a zero — it sorts last in either direction.
    if (x === null || x === undefined) return 1
    if (y === null || y === undefined) return -1
    return direction * (x - y)
  })
})

const visible = computed(() => sorted.value.slice(0, shown.value))

const expanded = ref(new Set())

function toggle(nmId) {
  const next = new Set(expanded.value)
  if (!next.delete(nmId)) next.add(nmId)
  expanded.value = next
}
</script>

<template>
  <div class="p-md">
    <div class="flex items-center gap-sm">
      <select
        v-model="sortKey"
        aria-label="Сортировка"
        class="min-h-11 min-w-0 flex-1 rounded-input border border-border-subtle bg-surface px-sm text-base text-primary"
      >
        <option v-for="option in SORT_KEYS" :key="option.key" :value="option.key">
          {{ option.label }}
        </option>
      </select>
      <button
        type="button"
        class="flex min-h-11 flex-none items-center gap-xs rounded-btn border border-border-subtle bg-surface px-md text-tiny font-medium text-primary transition hover:border-action hover:text-action"
        :aria-label="descending ? 'Сначала большие' : 'Сначала малые'"
        @click="descending = !descending"
      >
        {{ descending ? '↓ больше' : '↑ меньше' }}
      </button>
    </div>

    <p v-if="!rows.length" class="py-xl text-center text-base text-muted">Нет продаж за период</p>

    <ul v-else class="record-list mt-md">
      <li
        v-for="row in visible"
        :key="row.nmId ?? row.saName"
        class="record-card"
        :class="row.isExcluded && 'opacity-50'"
      >
        <!-- Two lines: who it is and what it earned, then the qualifiers. -->
        <button
          type="button"
          class="record-summary"
          :aria-expanded="expanded.has(row.nmId)"
          @click="toggle(row.nmId)"
        >
          <SkuThumb v-if="!row.isBucket" :src="row.photoUrl" :label="row.saName" size="sm" />
          <span class="record-main">
            <span class="record-title" :class="row.isBucket && 'font-normal text-muted'">
              {{ row.saName }}
            </span>
            <span class="record-sub">
              {{ row.isBucket ? 'на весь счёт' : row.nmId }}
              <template v-if="row.subject"> · {{ row.subject }}</template>
            </span>
          </span>

          <span class="record-figures">
            <span
              class="record-value"
              :class="row.profit !== null && row.profit < 0 && 'record-value--negative'"
            >
              {{ money(row.profit) }}
            </span>
            <span class="record-support">
              <span :class="toneClass('profitPct', row.profitPct)">{{ pct(row.profitPct) }}</span>
              · {{ money(row.sales) }}
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
          <div class="record-row">
            <span class="record-label">К перечислению</span>
            <span class="record-value">{{ money(row.payout) }}</span>
          </div>
          <div v-if="row.penalties" class="record-row">
            <span class="record-label">Штрафы</span>
            <span class="record-value record-value--negative">{{ money(row.penalties) }}</span>
          </div>
          <!-- The category is what tells a seller whether a fine is disputable,
               so it rides with the figure rather than being dropped. -->
          <p v-for="p in row.penaltyReasons" :key="p.reason" class="record-note">
            {{ p.reason }}: {{ money(p.amount) }}
          </p>
          <div v-if="row.brand" class="record-row">
            <span class="record-label">Бренд</span>
            <span class="record-value">{{ row.brand }}</span>
          </div>
          <div v-for="detail in DETAILS" :key="detail.label" class="record-row">
            <span class="record-label">{{ detail.label }}</span>
            <span class="record-value" :class="detail.tone?.(row)">
              {{ detail.get(row) }}
              <span
                v-if="detail.sub?.(row) && detail.sub(row) !== '—'"
                :class="detail.subTone?.(row) || 'text-muted'"
              >
                ({{ detail.sub(row) }})
              </span>
            </span>
          </div>
          <label v-if="!row.isBucket" class="record-row cursor-pointer">
            <span class="record-label">Не включать в общий счёт</span>
            <input
              type="checkbox"
              :checked="row.isExcluded"
              class="h-4 w-4 flex-none cursor-pointer rounded border-border-subtle text-action focus:ring-action/20"
              @change="
                emit('toggle-exclusion', { nmId: row.nmId, excluded: $event.target.checked })
              "
            />
          </label>
        </div>
      </li>
    </ul>

    <button
      v-if="shown < sorted.length"
      type="button"
      class="mt-sm min-h-11 w-full rounded-btn border border-border-subtle bg-surface text-base font-medium text-primary transition hover:border-action hover:text-action"
      @click="shown += PAGE"
    >
      Показать ещё ({{ sorted.length - shown }})
    </button>

    <PnlSkuCardsTotals v-if="totals" :totals="totals" />
  </div>
</template>

<style scoped src="./styles/RecordCards.css"></style>
