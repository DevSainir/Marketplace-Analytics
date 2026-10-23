<script setup>
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import MatrixEditToolbar from '@/modules/monitoring/components/MatrixEditToolbar.vue'
import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import MetricsChart from '@/modules/monitoring/components/MetricsChart.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
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
import { describeDetail } from '@/modules/monitoring/detailState'
import { MAX_PERIOD_DAYS, useSearchQuerySync } from '@/modules/monitoring/useSearchQuerySync'
import { useSkuClusters } from '@/modules/monitoring/useSkuClusters'
import { BackfillNotice, useWorkspaceStore } from '@/modules/profile'
import { formatSku } from '@/core/utils/format'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Handlers push a query; the watcher inside does all the fetching.
const { dateFrom, dateTo, windowTooWide, handleSelect, handleApply, applyPeriod } =
  useSearchQuerySync({ route, router, store })

/** Pick the search-relevant params out of a route query (arrays/absent → defaults). */
const product = computed(() => store.currentProduct)

const detailState = computed(() =>
  describeDetail({ windowTooWide: windowTooWide.value, product: product.value, store }),
)

// Vendor code (the seller's article) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(
  () => formatSku(product.value?.vendor_code) ?? `WB ID ${product.value?.nm_id ?? ''}`,
)

// --- global pinned SKUs ("Pin") -------------------------------------------
const isPinned = computed(() => product.value != null && store.pinnedIds.has(product.value.nm_id))

function togglePin() {
  if (!product.value) return
  store.toggleSkuPin(product.value.nm_id, product.value.vendor_code ?? null)
}

// --- the "Stock by warehouse" ribbon --------------------------------------
// Every day group shares one row set (see the helper for why). The days
// themselves come from the page's period, so there is nothing to pick here.
const sharedStockSizes = computed(() => unionStockSizes(store.stockDays))

// The daily table's whole editing surface: the rows it renders, the lock, the
// three commits it can make and the undo/redo keys.
const { matrix, editingLocked, onCellEdit, onCommentEdit, onActionEdit } = useMatrixEditing(store)

// --- "Search clusters": per workspace -------------------------------------
// Hidden for everyone on 2026-09-09 as a product decision, back on 2026-09-26
// for the workspaces whose `search_clusters_enabled` is set — today one workspace,
// turned on by migration `b5d2e8f41c93`. Everywhere else the block, its nav
// entry and its fetch stay off. The harvester fills `advertising_cluster_stat_daily`
// for every workspace regardless, so switching another workspace on later has
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
  { id: 'sec-matrix', label: 'By day' },
  { id: 'sec-stock', label: 'Stock' },
  { id: 'sec-chart', label: 'Chart' },
  ...(clustersEnabled.value ? [{ id: 'sec-clusters', label: 'Clusters' }] : []),
])

onMounted(() => store.fetchPins())
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <div class="app-container py-lg">
    <div class="w-full">
      <h1 class="sr-only">SKU monitoring</h1>
      <BackfillNotice :lanes="['catalogue', 'funnel', 'advertising']" />

      <!-- Period selector, slightly above the search bar; the bulk WB refresh
           sits beside it and stays visible with or without a SKU open. -->
      <div class="mb-sm flex flex-wrap items-start justify-between gap-sm">
        <PeriodSelector
          :from="dateFrom"
          :to="dateTo"
          :max-days="MAX_PERIOD_DAYS"
          @range="applyPeriod"
        />
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
        Couldn't load the SKU list: {{ store.skuListError }}
      </p>

      <SkuMatchPicker
        v-if="store.lookupMatches.length"
        :matches="store.lookupMatches"
        @select="handleSelect"
      />

      <DataState v-if="detailState" v-bind="detailState" class="mt-lg" />

      <!-- Product identity + daily metrics table after a SKU is submitted -->
      <BusyRegion v-else-if="product" :busy="store.loading">
        <DataState
          v-if="store.error"
          kind="error"
          layout="line"
          :text="store.error"
          class="mb-md"
        />
        <SkuIdentityHeader
          :product="product"
          :sku-label="skuLabel"
          :is-pinned="isPinned"
          @toggle-pin="togglePin"
        />

        <section id="sec-matrix" class="mt-lg" aria-label="Daily metrics">
          <h2 class="text-h3 font-semibold text-primary">Metrics by day</h2>

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
            <PeriodSelector
              :from="dateFrom"
              :to="dateTo"
              :max-days="MAX_PERIOD_DAYS"
              @range="applyPeriod"
            />
          </div>

          <MetricsChart :view="matrix" />
        </div>

        <!-- "Search clusters" — only for workspaces with the switch on;
             see the block comment in <script setup>. -->
        <div v-if="clustersEnabled" id="sec-clusters">
          <SkuClusterBlock v-bind="clusters.clusterTableProps" :currency="product?.ad_currencies" />
        </div>
      </BusyRegion>

      <!-- Initial state: an inviting hint until the first SKU is submitted -->
      <div v-else-if="!store.lookupMatches.length" class="mt-20 text-center phone:mt-xl">
        <p class="text-h2 font-semibold text-primary">Pick a SKU</p>
        <p class="mx-auto mt-sm max-w-xl text-base text-muted">
          Type a vendor code, WB ID or product name, or click the search bar and pick a SKU from the
          list. Its orders, advertising and stock appear here.
        </p>
      </div>
    </div>
  </div>
  <SectionNav :sections="SECTIONS" />
</template>
