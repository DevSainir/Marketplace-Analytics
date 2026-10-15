<script setup>
/**
 * The per-SKU P&L as a table — the desktop projection of `PnlSkuTable`.
 *
 * One row per SKU with the money columns of the reference workbook plus WB's
 * catalogue identity (the card photo / Артикул WB / Тип предмета / Бренд) and the efficiency
 * ratios (Выкуп, Средний чек, ROI). «Продажи» is shown NET of returns at the
 * page's price base (`priceBase.js`); the percentages are shares of it.
 *
 * «Штрафы» carry their categories inline — what tells a seller whether a fine
 * is disputable. The last column is the «Не включать» mark, emitted upward.
 * Rows cut by subject, brand or group (`isGroup`) are sums: no WB id, no mark.
 *
 * Three things beyond plain columns:
 *
 * * **Цвет только за рамкой.** Доли и коэффициенты подкрашены, когда вышли за
 *   границы из `pnlThresholds` — границы взяты по фактическому распределению,
 *   чтобы в обычном отчёте горели несколько строк, а не половина таблицы.
 * * **Размеры строками под артикулом.** Треугольник у артикула вставляет под
 *   ним его размеры в тех же колонках; грузятся по клику (`@load-sizes`).
 *   Своего «Итого» у размеров нет: их сумма — это строка артикула над ними.
 * * **Строка «Итого».** Закреплена внизу области прокрутки, считается по всему
 *   текущему фильтру, а не по странице пагинации.
 *
 * PrimeVue for the sticky header, the frozen first column and the sort arrows,
 * in `lazy` mode: the order and the page are `useSkuTreePage`'s, so sizes stay
 * under their article. What each cell shows is `pnlSkuCells`; this only lays
 * the columns out.
 */
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import Paginator from 'primevue/paginator'
import { ref, toRefs } from 'vue'

import InfoHint from '@/core/components/InfoHint.vue'
import { visibleArea } from '@/core/utils/tipFit'
import PnlExclusionToggle from '@/modules/finreports/components/PnlExclusionToggle.vue'
import PnlPenaltyReasons from '@/modules/finreports/components/PnlPenaltyReasons.vue'
import PnlSkuCell from '@/modules/finreports/components/PnlSkuCell.vue'
import PnlSkuRowIdentity from '@/modules/finreports/components/PnlSkuRowIdentity.vue'
import { COLUMNS, cellOf } from '@/modules/finreports/pnlSkuCells'
import { amountClass } from '@/modules/finreports/pnlThresholds'
import { pct, usePnlMoney } from '@/modules/finreports/pnlFormat'
import { usePriceBase } from '@/modules/finreports/priceBase'
import {
  useExpandedSkus,
  useFooterCells,
  useSkuTreePage,
} from '@/modules/finreports/usePnlSkuTable'

const props = defineProps({
  /** @type {Array<object>} Flattened rows from `usePnlSkuRows`, already filtered. */
  rows: { type: Array, default: () => [] },
  /** @type {object|null} The «Итого» row from `sumRows` — the whole filter, not the page. */
  totals: { type: Object, default: null },
  /** @type {object} `nm_id -> {loading, error, data}` for the opened articles. */
  sizes: { type: Object, default: () => ({}) },
  rowsPerPage: { type: Number, default: 50 },
  /** «Артикул», or «Предмет» / «Бренд» / «Группа» when the rows are sums. */
  firstHeader: { type: String, default: 'Артикул' },
  /** Whether an uncosted article's mark offers to enter its cost. */
  canEnterCost: { type: Boolean, default: false },
})

const emit = defineEmits(['toggle-exclusion', 'load-sizes', 'enter-cost'])

const { expanded, toggle } = useExpandedSkus(
  (nmId) => emit('load-sizes', nmId),
  () => props.sizes,
)
const { sortField, sortOrder, first, view } = useSkuTreePage({
  rows: toRefs(props).rows,
  perPage: () => props.rowsPerPage,
  expanded,
  sizes: () => props.sizes,
  base: usePriceBase(),
})

/** Reset to the first page on a size change — the parent sets it to 0. */
defineExpose({ first })

/** Excluded rows are dimmed; size rows read as part of the article above. */
const rowClass = (data) => [
  data.isExcluded && 'opacity-50',
  data.isOpen && 'pnl-tree-parent',
  data.kind && 'pnl-tree-child',
  data.isLast && 'pnl-tree-last',
]

const foot = useFooterCells(toRefs(props).totals)
const { money } = usePnlMoney()

/** The one «Причины штрафов» card: under the clicked «N причин», ending at its right edge. */
const reasons = ref(null)
const CARD_WIDTH_PX = 384
function toggleReasons(anchor, row, cell) {
  if (reasons.value?.key === row.rowKey) {
    reasons.value = null
    return
  }
  const rect = anchor.getBoundingClientRect()
  reasons.value = {
    key: row.rowKey,
    reasons: cell.reasons,
    top: rect.bottom + 6,
    left: rect.right - CARD_WIDTH_PX,
    area: visibleArea(anchor),
  }
}
</script>

<template>
  <div>
    <DataTable
      v-model:sort-field="sortField"
      v-model:sort-order="sortOrder"
      :value="view"
      lazy
      :row-class="rowClass"
      sort-mode="single"
      data-key="rowKey"
      scrollable
      scroll-height="min(40rem, 70vh)"
    >
      <template #empty>
        <div class="px-md py-xl text-center text-base text-muted">Нет продаж за период</div>
      </template>

      <!-- Фото и треугольник размеров живут в этой же закреплённой ячейке —
           почему именно так, написано в `PnlSkuRowIdentity`. -->
      <Column field="saName" :header="firstHeader" sortable frozen :footer="foot.saName">
        <template #body="{ data }">
          <span v-if="data.kind === 'size'" class="pnl-size-pill">{{ data.label }}</span>
          <span
            v-else-if="data.kind === 'note'"
            class="pl-lg text-tiny"
            :class="data.isError ? 'text-status-negative' : 'text-muted'"
            >{{ data.text }}</span
          >
          <PnlSkuRowIdentity
            v-else
            :row="data"
            :open="data.isOpen"
            :can-enter-cost="canEnterCost"
            @toggle="toggle(data.nmId)"
            @cost="emit('enter-cost', data)"
          />
        </template>
      </Column>
      <Column
        v-for="column in COLUMNS.slice(0, -1)"
        :key="column.field"
        :field="column.field"
        :header="column.hint ? undefined : column.header"
        :class="column.num && 'col-num'"
        sortable
        :footer="foot[column.field]"
      >
        <template v-if="column.hint" #header>
          {{ column.header }}<InfoHint :text="column.hint" />
        </template>
        <template #body="{ data }">
          <PnlSkuCell
            :cell="cellOf(column, data, money)"
            @reasons="toggleReasons($event, data, cellOf(column, data, money))"
          />
        </template>
      </Column>
      <Column field="profit" class="col-num" header="Чистая прибыль" sortable>
        <template #body="{ data }">
          <PnlSkuCell :cell="cellOf(COLUMNS.at(-1), data, money)" />
        </template>
        <template #footer>
          <span v-if="totals" :class="amountClass(totals.profit)">
            {{ money(totals.profit) }}
            <span class="text-tiny text-muted">({{ pct(totals.profitPct) }})</span>
          </span>
        </template>
      </Column>
      <Column field="isExcluded" header="" :sortable="false">
        <template #body="{ data }">
          <PnlExclusionToggle
            v-if="data.isSku"
            :checked="data.isExcluded"
            @change="emit('toggle-exclusion', { nmId: data.nmId, excluded: $event })"
          />
        </template>
      </Column>
    </DataTable>
    <PnlPenaltyReasons :open="reasons" @close="reasons = null" />
    <Paginator
      v-if="rows.length > rowsPerPage"
      v-model:first="first"
      :rows="rowsPerPage"
      :total-records="rows.length"
    />
  </div>
</template>
