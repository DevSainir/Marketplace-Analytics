<script setup>
/**
 * Day-by-day metrics table (dumb): a horizontal ribbon of day sections, each
 * one the workbook's 7-column «тип трафика × зона показов» block, newest day
 * on the right. Auto-scrolls to the newest day whenever a new matrix arrives;
 * the metric-name column stays frozen on the left while scrolling (see
 * `.app-datatable--matrix` skin in main.css).
 *
 * Header (3 rows, as in the workbook):
 *   Дата · Тип получения трафика (groups) · Зоны показов (leaf columns).
 */
import Column from 'primevue/column'
import ColumnGroup from 'primevue/columngroup'
import DataTable from 'primevue/datatable'
import Row from 'primevue/row'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { TRAFFIC_COLUMNS, TRAFFIC_GROUPS } from '@/modules/monitoring/metricsMatrix'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** @type {Array<{key, label, values: string[]}>} day-major preformatted cells */
  rows: { type: Array, required: true },
})

// One leaf column per day × traffic column; `index` addresses row.values.
const leafColumns = computed(() =>
  props.days.flatMap((day, dayIndex) =>
    TRAFFIC_COLUMNS.map((column, columnIndex) => ({
      id: `${day.iso}:${column.key}`,
      key: column.key,
      zone: column.zone,
      index: dayIndex * TRAFFIC_COLUMNS.length + columnIndex,
    })),
  ),
)

// «Общая»/«Органика» cells span the zones row (rowspan=2 in the type row),
// so the zones row only lists the columns that actually have a zone split.
const zonedGroupKeys = new Set(['uni_search', 'uni_shelves', 'uni_catalog', 'manual_search', 'manual_shelves'])
const zoneHeaderColumns = computed(() => leafColumns.value.filter((leaf) => zonedGroupKeys.has(leaf.key)))

// Metric accents: «Затраты» warning, «Заказы»/«Конверсия в заказ» positive,
// «Корзины»/«Конверсия в корзину» indigo. Labels always; cells only when filled.
const TONE_CLASSES = {
  warning: 'text-status-warning',
  positive: 'text-status-positive',
  carts: 'text-accent-indigo',
}

function cellClass(row, value) {
  if (!row.tone || value === '—') return 'text-primary'
  return TONE_CLASSES[row.tone]
}

const root = ref(null)

/** Start at the right edge: «сегодня» first, older days appear as you scroll left. */
function scrollToNewestDay() {
  const container = root.value?.querySelector("[data-pc-section='tablecontainer']")
  if (container) container.scrollLeft = container.scrollWidth
}

onMounted(scrollToNewestDay)
watch(
  () => props.days,
  () => nextTick(scrollToNewestDay),
)
</script>

<template>
  <!-- --matrix-days drives the fixed-layout width so EXACTLY two day
       sections fill the viewport (see .app-datatable--matrix in main.css). -->
  <div ref="root" class="app-datatable app-datatable--matrix" :style="`--matrix-days: ${days.length}`">
    <DataTable :value="rows" data-key="key">
      <template #empty>
        <div class="px-md py-xl text-center text-base text-muted">
          Нет данных за выбранный период.
        </div>
      </template>

      <ColumnGroup type="header">
        <Row>
          <Column header="Дата" />
          <Column v-for="day in days" :key="day.iso" :header="day.label" :colspan="7" />
        </Row>
        <Row>
          <Column header="Тип получения трафика" />
          <template v-for="day in days" :key="day.iso">
            <Column
              v-for="group in TRAFFIC_GROUPS"
              :key="`${day.iso}:${group.label}`"
              :header="group.label"
              :colspan="group.span"
              :rowspan="group.spansZones ? 2 : 1"
            />
          </template>
        </Row>
        <Row>
          <Column header="Зоны показов" />
          <Column v-for="leaf in zoneHeaderColumns" :key="leaf.id" :header="leaf.zone" />
        </Row>
      </ColumnGroup>

      <Column field="label">
        <template #body="{ data }">
          <span class="font-medium" :class="data.tone ? TONE_CLASSES[data.tone] : 'text-primary'">
            {{ data.label }}
          </span>
        </template>
      </Column>

      <Column v-for="leaf in leafColumns" :key="leaf.id">
        <template #body="{ data }">
          <span class="tabular-nums" :class="cellClass(data, data.values[leaf.index])">
            {{ data.values[leaf.index] }}
          </span>
        </template>
      </Column>
    </DataTable>
  </div>
</template>
