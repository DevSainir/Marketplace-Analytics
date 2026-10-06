/**
 * The metrics table's column model: which columns a given metric row spans.
 *
 * Almost every row lays out one leaf column per day x traffic column. Two do
 * not, and that exception is the whole reason this is a module rather than an
 * inline computed: «ДРР от продаж» belongs to a CAMPAIGN (all of its view
 * zones) and «Процент выкупа» to the whole DAY, so each merges cells
 * Excel-style over its own wider columns. `index` still addresses `row.cells`
 * in every case, pointing at the cell that carries the value.
 *
 * Pure and derived from `days` alone, so it is testable without mounting the
 * table.
 */
import { computed } from 'vue'

import {
  DAY_SPAN_COLUMNS,
  DRR_SALES_COLUMNS,
  TRAFFIC_COLUMNS,
} from '@/modules/monitoring/metricsMatrix'

/** Rows that merge cells instead of rendering all leaf columns. */
const MERGED_ROW_COLUMNS = {
  drr_sales: DRR_SALES_COLUMNS,
  buyout_percent: DAY_SPAN_COLUMNS,
}

// «Общая»/«Органика» cells span the zones row (rowspan=2 in the type row), so
// the zones row only lists the columns that actually have a zone split.
const ZONED_GROUP_KEYS = new Set([
  'uni_search',
  'uni_shelves',
  'manual_search',
  'manual_catalog',
  'manual_shelves',
  'cpc_search',
  'cpc_shelves',
])

/**
 * @param {() => Array<{iso: string}>} days Reactive accessor for the day list.
 */
export function useMatrixColumns(days) {
  const leafColumns = computed(() =>
    days().flatMap((day, dayIndex) =>
      TRAFFIC_COLUMNS.map((column, columnIndex) => ({
        id: `${day.iso}:${column.key}`,
        key: column.key,
        zone: column.zone,
        index: dayIndex * TRAFFIC_COLUMNS.length + columnIndex,
      })),
    ),
  )

  const mergedColumns = computed(() =>
    Object.fromEntries(
      Object.entries(MERGED_ROW_COLUMNS).map(([rowKey, columns]) => [
        rowKey,
        days().flatMap((day, dayIndex) =>
          columns.map((column) => ({
            id: `${day.iso}:${column.key}`,
            key: column.key,
            span: column.span,
            colspan: column.span,
            index: dayIndex * TRAFFIC_COLUMNS.length + column.offset,
          })),
        ),
      ]),
    ),
  )

  const zoneHeaderColumns = computed(() =>
    leafColumns.value.filter((leaf) => ZONED_GROUP_KEYS.has(leaf.key)),
  )

  /** The column set a metric row renders over (merged for the two rows above). */
  function rowColumns(row) {
    return mergedColumns.value[row.key] ?? leafColumns.value
  }

  return { leafColumns, zoneHeaderColumns, rowColumns }
}
