<script setup>
/**
 * The heatmap grid: one row per article (or category, brand, group), one column
 * per day, week or month, every cell painted by where it sits between the worst
 * and the best.
 *
 * A plain `<table>` rather than PrimeVue's DataTable, and on purpose. What this
 * grid needs is a tint on EVERY cell, and the DataTable's column API styles a
 * whole column at once; its sort would have to be replaced (empty cells must
 * sink whichever way a column is sorted) and so would its paginator (the page
 * size sits under the grid, not in it). With all three overridden, what was
 * left of it was sticky positioning, which here is four CSS rules — the header,
 * the «Итого» line under it, and the two left columns.
 *
 * Columns run oldest to newest, left to right, as in the monitoring matrix,
 * and every new grid opens scrolled to its RIGHT end: on a long window the
 * reader lands on yesterday, not on the first day of the range.
 *
 * With «Норма: ручной ввод» a «Норма «…»» column follows the article one —
 * sticky with it, named after the painted metric so it is plain which metric
 * the number belongs to.
 *
 * Dumb by contract: rows, their tints, norms and the sort in; header clicks and
 * norm edits out.
 */
import { computed, nextTick, ref, watch } from 'vue'

import DataState from '@/core/components/DataState.vue'
import SortIcon from '@/core/components/SortIcon.vue'
import SkuThumb from '@/core/components/SkuThumb.vue'
import HeatmapNormInput from '@/modules/heatmap/components/HeatmapNormInput.vue'
import { formatSku } from '@/core/utils/format'
import { columnLabel, monitoringLink, storefrontUrl } from '@/modules/heatmap/grid'
import { addsUp, cellText } from '@/modules/heatmap/metrics'

const props = defineProps({
  columns: { type: Array, required: true },
  period: { type: String, required: true },
  /** The rows on this page, already sorted. */
  rows: { type: Array, required: true },
  /** One style (background) per cell of each row, from `tintRows`. */
  tints: { type: Array, required: true },
  totals: { type: Object, default: null },
  primary: { type: Object, required: true },
  secondary: { type: Object, default: null },
  sort: { type: Object, required: true },
  groupBy: { type: String, required: true },
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
  /** `(nmId) => number|null` while norms are typed by hand; `null` hides the column. */
  normOf: { type: Function, default: null },
  /** The grid's currencies — prices, advertising, settlement — for the figures' signs. */
  currencies: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['sort', 'norm'])

const wrap = ref(null)

// A new response (not a sort or a page flip, which keep the same columns
// array) scrolls to the newest day; the article and «Итого» columns stay put.
watch(
  () => props.columns,
  async () => {
    await nextTick()
    if (wrap.value) wrap.value.scrollLeft = wrap.value.scrollWidth
  },
  { immediate: true },
)

const NAME_HEADERS = { sku: 'Артикул', subject: 'Предмет', brand: 'Бренд', group: 'Группа' }

/** What `SortIcon` draws for a column: not the sort, or which way it runs. */
function sortState(by) {
  if (props.sort.by !== by) return 'none'
  return props.sort.dir === 'desc' ? 'desc' : 'asc'
}

function ariaSort(by) {
  if (props.sort.by !== by) return 'none'
  return props.sort.dir === 'desc' ? 'descending' : 'ascending'
}

// «в день» only where a week multiplies it — a CTR norm is the week's CTR too.
const normTitle = computed(
  () => `Норма «${props.primary.label}»${addsUp(props.primary) ? ' в день' : ''}`,
)

const top = (row, at) => cellText(row, at, props.primary, props.currencies)
const bottom = (row, at) => cellText(row, at, props.secondary, props.currencies, true)
</script>

<template>
  <div ref="wrap" class="hm-grid-wrap">
    <table class="hm-grid" :class="{ 'hm-grid--norm': normOf }">
      <thead>
        <tr>
          <th class="hm-grid__name">{{ NAME_HEADERS[groupBy] }}</th>
          <th v-if="normOf" class="hm-grid__norm">{{ normTitle }}</th>
          <th class="hm-grid__total" :aria-sort="ariaSort('total')">
            <button type="button" class="hm-grid__sort" @click="emit('sort', 'total')">
              Итого<SortIcon :state="sortState('total')" />
            </button>
          </th>
          <th v-for="(column, index) in columns" :key="column.start" :aria-sort="ariaSort(index)">
            <button type="button" class="hm-grid__sort" @click="emit('sort', index)">
              {{ columnLabel(column, period) }}
              <SortIcon :state="sortState(index)" />
            </button>
          </th>
        </tr>
      </thead>

      <tbody>
        <tr v-if="totals" class="hm-grid__totals">
          <td class="hm-grid__name">Итого</td>
          <td v-if="normOf" class="hm-grid__norm"></td>
          <td class="hm-grid__total">
            <span class="hm-grid__top">{{ top(totals, 'total') }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(totals, 'total') }}</span>
          </td>
          <td v-for="(_value, index) in totals.values" :key="index">
            <span class="hm-grid__top">{{ top(totals, index) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(totals, index) }}</span>
          </td>
        </tr>

        <tr v-for="(row, rowIndex) in rows" :key="row.key">
          <td class="hm-grid__name">
            <div v-if="row.nm_id" class="flex min-w-0 items-center gap-sm">
              <SkuThumb :src="row.photo_url" :label="row.label" />
              <a
                class="hm-wb"
                :href="storefrontUrl(row.nm_id)"
                target="_blank"
                rel="noopener noreferrer"
                :aria-label="`Карточка ${formatSku(row.label)} на Wildberries`"
                >wb</a
              >
              <RouterLink
                class="min-w-0 truncate text-action hover:underline"
                :to="monitoringLink(row.nm_id, dateFrom, dateTo)"
                :title="row.title"
              >
                {{ formatSku(row.label) ?? `Артикул WB ${row.nm_id}` }}
              </RouterLink>
            </div>
            <div v-else class="flex min-w-0 items-baseline gap-sm">
              <span class="truncate">{{ row.label }}</span>
              <span class="shrink-0 text-tiny text-muted">{{ row.sku_count }} арт.</span>
            </div>
          </td>
          <td v-if="normOf" class="hm-grid__norm">
            <HeatmapNormInput
              :value="normOf(row.nm_id)"
              :label="`${normTitle} для ${formatSku(row.label) ?? row.nm_id}`"
              @commit="emit('norm', row.nm_id, $event)"
            />
          </td>
          <td class="hm-grid__total">
            <span class="hm-grid__top">{{ top(row, 'total') }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(row, 'total') }}</span>
          </td>
          <td v-for="(_value, index) in row.values" :key="index" :style="tints[rowIndex]?.[index]">
            <span class="hm-grid__top">{{ top(row, index) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(row, index) }}</span>
          </td>
        </tr>
      </tbody>
    </table>

    <DataState v-if="!rows.length" kind="empty" layout="bare" />
  </div>
</template>
