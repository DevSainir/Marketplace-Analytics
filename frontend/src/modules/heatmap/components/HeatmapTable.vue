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
 * Dumb by contract: rows, their tints and the sort in; header clicks out.
 */
import SkuThumb from '@/core/components/SkuThumb.vue'
import { formatSku } from '@/core/utils/format'
import { columnLabel, monitoringLink, storefrontUrl } from '@/modules/heatmap/grid'
import { formatValue } from '@/modules/heatmap/metrics'

const props = defineProps({
  columns: { type: Array, required: true },
  period: { type: String, required: true },
  /** The rows on this page, already sorted. */
  rows: { type: Array, required: true },
  /** One CSS background per cell of each row, from `tintRows`. */
  tints: { type: Array, required: true },
  totals: { type: Object, default: null },
  primary: { type: Object, required: true },
  secondary: { type: Object, default: null },
  sort: { type: Object, required: true },
  groupBy: { type: String, required: true },
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
})
const emit = defineEmits(['sort'])

const NAME_HEADERS = { sku: 'Артикул', subject: 'Категория', brand: 'Бренд', group: 'Группа' }

function arrow(by) {
  if (props.sort.by !== by) return '↕'
  return props.sort.dir === 'desc' ? '↓' : '↑'
}

function ariaSort(by) {
  if (props.sort.by !== by) return 'none'
  return props.sort.dir === 'desc' ? 'descending' : 'ascending'
}

const top = (value) => formatValue(value, props.primary.unit)
const bottom = (value) => formatValue(value, props.secondary?.unit ?? 'count')
</script>

<template>
  <div class="hm-grid-wrap">
    <table class="hm-grid">
      <thead>
        <tr>
          <th class="hm-grid__name">{{ NAME_HEADERS[groupBy] }}</th>
          <th class="hm-grid__total" :aria-sort="ariaSort('total')">
            <button type="button" class="hm-grid__sort" @click="emit('sort', 'total')">
              Итого <span aria-hidden="true">{{ arrow('total') }}</span>
            </button>
          </th>
          <th v-for="(column, index) in columns" :key="column.start" :aria-sort="ariaSort(index)">
            <button type="button" class="hm-grid__sort" @click="emit('sort', index)">
              {{ columnLabel(column, period) }}
              <span aria-hidden="true">{{ arrow(index) }}</span>
            </button>
          </th>
        </tr>
      </thead>

      <tbody>
        <tr v-if="totals" class="hm-grid__totals">
          <td class="hm-grid__name">Итого</td>
          <td class="hm-grid__total">
            <span class="hm-grid__top">{{ top(totals.total) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(totals.total2) }}</span>
          </td>
          <td v-for="(value, index) in totals.values" :key="index">
            <span class="hm-grid__top">{{ top(value) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{
              bottom(totals.values2[index])
            }}</span>
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
                {{ formatSku(row.label) ?? `SKU ${row.nm_id}` }}
              </RouterLink>
            </div>
            <div v-else class="flex min-w-0 items-baseline gap-sm">
              <span class="truncate">{{ row.label }}</span>
              <span class="shrink-0 text-tiny text-muted">{{ row.sku_count }} арт.</span>
            </div>
          </td>
          <td class="hm-grid__total">
            <span class="hm-grid__top">{{ top(row.total) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(row.total2) }}</span>
          </td>
          <td
            v-for="(value, index) in row.values"
            :key="index"
            :style="{ background: tints[rowIndex]?.[index] || undefined }"
          >
            <span class="hm-grid__top">{{ top(value) }}</span>
            <span v-if="secondary" class="hm-grid__bottom">{{ bottom(row.values2[index]) }}</span>
          </td>
        </tr>
      </tbody>
    </table>

    <p v-if="!rows.length" class="px-md py-xl text-center text-base text-muted">
      За период нет данных по выбранным артикулам.
    </p>
  </div>
</template>
