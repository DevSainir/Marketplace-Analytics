<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isoDaysAgo } from '@/core/utils/dates'

import MatrixEditToolbar from '@/modules/monitoring/components/MatrixEditToolbar.vue'
import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import SkuIdentityHeader from '@/modules/monitoring/components/SkuIdentityHeader.vue'
import SkuMatchPicker from '@/modules/monitoring/components/SkuMatchPicker.vue'
import PinnedSkuRow from '@/modules/monitoring/components/PinnedSkuRow.vue'
import RefreshAllSkusButton from '@/modules/monitoring/components/RefreshAllSkusButton.vue'
import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'
import StockComparePanel from '@/modules/monitoring/components/StockComparePanel.vue'
import { useMonitoringStore } from '@/modules/monitoring/store'
import { useMatrixHistoryKeys } from '@/modules/monitoring/useMatrixHistoryKeys'
import { useSearchQuerySync } from '@/modules/monitoring/useSearchQuerySync'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Default inclusive window: the last 30 days INCLUDING today — the funnel has
// no current-day data yet (blank cells), but today's price/stock snapshots
// must already show.
const DEFAULT_FROM = isoDaysAgo(30)
const DEFAULT_TO = isoDaysAgo(0)

// Handlers push a query; the watcher inside does all the fetching.
const { dateFrom, dateTo, handleSelect, handleApply } = useSearchQuerySync({
  route,
  router,
  store,
  defaults: { from: DEFAULT_FROM, to: DEFAULT_TO },
})

/** Pick the search-relevant params out of a route query (arrays/absent → defaults). */
const product = computed(() => store.currentProduct)

// Vendor code (артикул продавца) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(() => product.value?.vendor_code ?? `SKU ${product.value?.nm_id ?? ''}`)

// --- global pinned SKUs («Закрепить») -------------------------------------
const isPinned = computed(() => product.value != null && store.pinnedIds.has(product.value.nm_id))

function togglePin() {
  if (!product.value) return
  store.toggleSkuPin(product.value.nm_id, product.value.vendor_code ?? null)
}

// --- day notes («Комментарий» + its header) ---------------------------------
// Notes live per DAY inside the metrics table (its collapsible «Комментарии»
// row), so the view only forwards the commit to the store. The patch carries
// just the edited field — header and comment save independently.
function handleCommentEdit({ day, patch }) {
  store.saveDayComment(day, patch)
}

// --- day actions («Действия») ----------------------------------------------
// The per-day РК/price answers live in their own row of the metrics table; the
// view only forwards each partial change to the store, which merges + saves.
function handleActionEdit({ day, patch }) {
  store.saveDayAction(day, patch)
}

// --- two-day stock comparison ----------------------------------------------
// Both side-by-side tables render the UNION of the two days' sizes so their
// rows align 1:1 (a size absent on one day shows blank there) — each table
// carries its own «Размер» column, so the labels repeat by design: it keeps
// each day readable on its own, and the pair still compares row by row.
const sharedStockSizes = computed(() => {
  const byChrt = new Map()
  for (const side of ['left', 'right']) {
    for (const cell of store.stockCompare[side].stock?.cells ?? []) {
      if (!byChrt.has(cell.chrt_id)) byChrt.set(cell.chrt_id, cell.tech_size ?? null)
    }
  }
  const label = (size) => size.tech_size ?? `chrt ${size.chrt_id}`
  return [...byChrt.entries()]
    .map(([chrt_id, tech_size]) => ({ chrt_id, tech_size }))
    .sort((a, b) => label(a).localeCompare(label(b), 'ru', { numeric: true }))
})

function onStockDayChange(side, iso) {
  if (iso) store.fetchStockCompareSide(side, iso)
}

// Metric rows × day columns for the daily table (workbook replica). The store
// owns this reactive structure and patches cells in place on edit/undo/redo so
// the table doesn't fully re-render.
const metricsMatrix = computed(() => store.matrixView)

// Editing is locked while a save or WB refresh is in flight.
const editingLocked = computed(() => store.matrixSaving || store.matrixRefreshing)

/** A cell edit: hand the raw value to the store (backend recomputes dependents). */
function handleCellEdit(edit) {
  store.applyCellEdit(edit)
}

// History keys: Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z (or Ctrl/Cmd+Y) redoes.
// Ignored while typing in an input and while a save/refresh is running.
useMatrixHistoryKeys({
  undo: () => store.canUndoMatrix && store.undoMatrixEdit(),
  redo: () => store.canRedoMatrix && store.redoMatrixEdit(),
  locked: () => editingLocked.value,
})

onMounted(() => store.fetchPins())
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <div class="app-container py-lg">
    <div class="w-full">
      <h1 class="sr-only">Мониторинг SKU</h1>

      <!-- Period selector, slightly above the search bar; the bulk WB refresh
           sits beside it and stays visible with or without a SKU open. -->
      <div class="mb-sm flex flex-wrap items-start justify-between gap-sm">
        <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" />
        <RefreshAllSkusButton
          :refreshing="store.allRefreshing"
          :error="store.allRefreshError"
          :warning="store.allRefreshWarning"
          @refresh="store.refreshAllFromWb()"
        />
      </div>

      <!-- Search bar: apply on the left, dropdown with all SKUs below -->
      <SkuSearchSelect
        :items="store.skuList"
        :loading="store.skuListLoading"
        :selected-id="product?.nm_id ?? null"
        @select="handleSelect"
        @apply="handleApply"
      />

      <!-- Global pinned SKUs: chips to jump between watched SKUs, draggable to
           reorder, paintable via the palette at the row's right edge. -->
      <PinnedSkuRow
        v-if="store.pinnedSkus.length"
        :items="store.pinnedSkus"
        :selected-id="product?.nm_id ?? null"
        @select="handleSelect"
        @reorder="store.reorderPins"
        @recolor="store.setPinColor"
      />

      <p v-if="store.skuListError" class="mt-sm text-tiny text-status-negative">
        Не удалось загрузить список SKU: {{ store.skuListError }}
      </p>

      <SkuMatchPicker
        v-if="store.lookupMatches.length"
        :matches="store.lookupMatches"
        @select="handleSelect"
      />

      <!-- Detail states -->
      <p v-if="store.loading" class="mt-lg text-center text-base text-muted">
        Загружаем статистику {{ skuLabel }}…
      </p>

      <div
        v-else-if="store.error"
        class="mt-lg rounded-card bg-status-negative/10 p-md text-base text-status-negative"
      >
        <p class="font-semibold">Не удалось загрузить данные</p>
        <p class="mt-xs">{{ store.error }}</p>
      </div>

      <p v-else-if="store.notFound" class="mt-lg text-center text-base text-muted">
        По артикулу «{{ store.notFound }}» ничего не найдено.
      </p>

      <!-- Product identity + daily metrics table after a SKU is submitted -->
      <template v-else-if="product">
        <SkuIdentityHeader
          :product="product"
          :sku-label="skuLabel"
          :is-pinned="isPinned"
          @toggle-pin="togglePin"
        />

        <section class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable
            class="mt-sm"
            :days="metricsMatrix.days"
            :rows="metricsMatrix.rows"
            :price-rows="metricsMatrix.priceRows"
            :stock-rows="metricsMatrix.stockRows"
            :stock-total-rows="metricsMatrix.stockTotalRows"
            :comments="product.comments ?? {}"
            :comment-saving-days="store.commentSavingDays"
            :day-actions="product.day_actions ?? {}"
            :action-saving-days="store.actionSavingDays"
            :editing-disabled="editingLocked"
            @edit="handleCellEdit"
            @comment="handleCommentEdit"
            @action="handleActionEdit"
          />

          <MatrixEditToolbar
            :dirty="store.matrixDirty"
            :saving="store.matrixSaving"
            :refreshing="store.matrixRefreshing"
            :loading="store.loading"
            :error="store.actionError"
            :warning="store.actionWarning"
            @save="store.saveMatrixEdits()"
            @refresh="store.refreshFromWb()"
          />
        </section>

        <StockComparePanel
          v-if="product.stock"
          :sides="store.stockCompare"
          :marked-warehouses="store.markedWarehouses"
          :size-order="sharedStockSizes"
          :max-date="DEFAULT_TO"
          @change-day="onStockDayChange"
          @toggle-mark="store.toggleWarehouseMark"
        />
      </template>

      <!-- Initial state: an inviting hint until the first SKU is submitted -->
      <div v-else-if="!store.lookupMatches.length" class="mt-20 text-center phone:mt-xl">
        <p class="text-h2 font-semibold text-primary">Введите артикул товара</p>
        <p class="mx-auto mt-sm max-w-xl text-base text-muted">
          Начните вводить артикул продавца, nm ID или название — либо просто кликните по строке
          поиска и выберите SKU из списка. После этого здесь появится короткая сводка по заказам,
          рекламе и остаткам.
        </p>
      </div>
    </div>
  </div>
</template>
