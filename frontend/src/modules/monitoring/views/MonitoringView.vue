<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { MAX_WINDOW_DAYS, isoDaysAgo } from '@/core/utils/dates'

import MatrixEditToolbar from '@/modules/monitoring/components/MatrixEditToolbar.vue'
import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import MetricsChart from '@/modules/monitoring/components/MetricsChart.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import SkuIdentityHeader from '@/modules/monitoring/components/SkuIdentityHeader.vue'
import SkuMatchPicker from '@/modules/monitoring/components/SkuMatchPicker.vue'
import PinnedSkuRow from '@/modules/monitoring/components/PinnedSkuRow.vue'
import RefreshAllSkusButton from '@/modules/monitoring/components/RefreshAllSkusButton.vue'
import SectionNav from '@/core/components/SectionNav.vue'
import SkuClusterBlock from '@/modules/monitoring/components/SkuClusterBlock.vue'
import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'
import StockComparePanel from '@/modules/monitoring/components/StockComparePanel.vue'
import { useMonitoringStore } from '@/modules/monitoring/store'
import { useMatrixEditing } from '@/modules/monitoring/useMatrixEditing'
import { unionStockSizes } from '@/modules/monitoring/stockCompareSizes'
import { useSearchQuerySync } from '@/modules/monitoring/useSearchQuerySync'
import { useSkuClusters } from '@/modules/monitoring/useSkuClusters'
import { useWorkspaceStore } from '@/modules/profile'
import { formatSku } from '@/core/utils/format'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Default inclusive window: the last 30 days INCLUDING today — the funnel has
// no current-day data yet (blank cells), but today's price/stock snapshots
// must already show.
const DEFAULT_FROM = isoDaysAgo(30)
const DEFAULT_TO = isoDaysAgo(0)

// Handlers push a query; the watcher inside does all the fetching.
const { dateFrom, dateTo, windowTooWide, handleSelect, handleApply, applyPeriod } =
  useSearchQuerySync({
    route,
    router,
    store,
    defaults: { from: DEFAULT_FROM, to: DEFAULT_TO },
  })

/** Pick the search-relevant params out of a route query (arrays/absent → defaults). */
const product = computed(() => store.currentProduct)

// Vendor code (артикул продавца) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(
  () => formatSku(product.value?.vendor_code) ?? `SKU ${product.value?.nm_id ?? ''}`,
)

// --- global pinned SKUs («Закрепить») -------------------------------------
const isPinned = computed(() => product.value != null && store.pinnedIds.has(product.value.nm_id))

function togglePin() {
  if (!product.value) return
  store.toggleSkuPin(product.value.nm_id, product.value.vendor_code ?? null)
}

// --- the «Остатки по складам» ribbon ---------------------------------------
// Every day group shares one row set (see the helper for why). The days
// themselves come from the page's period, so there is nothing to pick here.
const sharedStockSizes = computed(() => unionStockSizes(store.stockDays))

// The daily table's whole editing surface: the rows it renders, the lock, the
// three commits it can make and the undo/redo keys.
const { matrix, editingLocked, onCellEdit, onCommentEdit, onActionEdit } = useMatrixEditing(store)

// --- «Рекламные кластеры»: per кабинет ------------------------------------
// Hidden for everyone on 2026-09-09 as a product decision, back on 2026-09-26
// for the workspaces whose `search_clusters_enabled` is set — today only NEVA,
// turned on by migration `b5d2e8f41c93`. Everywhere else the block, its nav
// entry and its fetch stay off. The harvester fills `advertising_cluster_stat_daily`
// for every workspace regardless, so switching another кабинет on later has
// its history ready.
const workspaces = useWorkspaceStore()
const clustersEnabled = computed(() =>
  Boolean(workspaces.currentWorkspace?.search_clusters_enabled),
)
const clusters = useSkuClusters(() => clustersEnabled.value)

/**
 * Targets for the floating section nav. The blocks own their own <section>
 * markup and take no id prop, so the anchors are wrapper divs in the template.
 */
const SECTIONS = computed(() => [
  { id: 'sec-matrix', label: 'По дням' },
  { id: 'sec-stock', label: 'Остатки' },
  { id: 'sec-chart', label: 'График' },
  ...(clustersEnabled.value ? [{ id: 'sec-clusters', label: 'Кластеры' }] : []),
])

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
        <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" @apply="applyPeriod" />
        <RefreshAllSkusButton
          :refreshing="store.allRefreshing"
          :progress="store.allRefreshProgress"
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

      <p v-if="store.skuListError && !windowTooWide" class="mt-sm text-tiny text-status-negative">
        Не удалось загрузить список SKU: {{ store.skuListError }}
      </p>

      <SkuMatchPicker
        v-if="store.lookupMatches.length"
        :matches="store.lookupMatches"
        @select="handleSelect"
      />

      <!-- Detail states. The window bound leads, said as a bound and not a fault. -->
      <p v-if="windowTooWide" class="mt-lg text-base text-muted">
        Период больше {{ MAX_WINDOW_DAYS }} дней не показываем — выберите отрезок покороче, и данные
        появятся снова.
      </p>

      <p v-else-if="store.loading" class="mt-lg text-center text-base text-muted">
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

        <section id="sec-matrix" class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable
            class="mt-sm"
            :days="matrix.days"
            :rows="matrix.rows"
            :price-rows="matrix.priceRows"
            :stock-rows="matrix.stockRows"
            :stock-total-rows="matrix.stockTotalRows"
            :comments="product.comments ?? {}"
            :comment-saving-days="store.commentSavingDays"
            :day-actions="product.day_actions ?? {}"
            :action-saving-days="store.actionSavingDays"
            :editing-disabled="editingLocked"
            :campaigns="matrix.campaigns"
            @edit="onCellEdit"
            @comment="onCommentEdit"
            @action="onActionEdit"
          />

          <MatrixEditToolbar
            :dirty="store.matrixDirty"
            :saving="store.matrixSaving"
            :refreshing="store.matrixRefreshing"
            :progress="store.refreshProgress"
            :loading="store.loading"
            :error="store.actionError"
            :warning="store.actionWarning"
            @save="store.saveMatrixEdits()"
            @refresh="store.refreshFromWb()"
          />
        </section>

        <div id="sec-stock">
          <StockComparePanel
            v-if="product.stock"
            :days="store.stockDays"
            :size-order="sharedStockSizes"
            :loading="store.stockDaysLoading"
          />
        </div>

        <div id="sec-chart">
          <!-- The page's own control again: by here the top one is offscreen. -->
          <div class="mt-lg flex justify-end">
            <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" @apply="applyPeriod" />
          </div>

          <MetricsChart :view="matrix" />
        </div>

        <!-- «Рекламные кластеры» — only for кабинеты with the switch on (NEVA);
             see the block comment in <script setup>. -->
        <div v-if="clustersEnabled" id="sec-clusters">
          <SkuClusterBlock v-bind="clusters.clusterTableProps" />
        </div>
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
  <SectionNav :sections="SECTIONS" />
</template>
