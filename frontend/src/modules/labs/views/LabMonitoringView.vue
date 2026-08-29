<script setup>
/**
 * DESIGN SANDBOX — /monitoring on a second design system.
 *
 * The components under `labs/components/` are VERBATIM copies of the
 * monitoring ones: same markup, same props, same behaviour, only their import
 * paths rewritten. This view composes them in the same order
 * `MonitoringView.vue` does, and the data comes from `fixtures.js` through the
 * real `buildMetricsMatrix`.
 *
 * Nothing structural is re-implemented here, so every difference you can see
 * between the two pages comes from one stylesheet — `skin.css`, which
 * re-points the design tokens the copied markup already asks for.
 */
import { computed, ref } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import MatrixEditToolbar from '@/modules/labs/components/MatrixEditToolbar.vue'
import MetricsChart from '@/modules/labs/components/MetricsChart.vue'
import MetricsTable from '@/modules/labs/components/MetricsTable.vue'
import SectionNav from '@/core/components/SectionNav.vue'
import UiBlockOrbs from '@/core/components/UiBlockOrbs.vue'
import PinnedSkuRow from '@/modules/labs/components/PinnedSkuRow.vue'
import RefreshAllSkusButton from '@/modules/labs/components/RefreshAllSkusButton.vue'
import SkuClusterBlock from '@/modules/labs/components/SkuClusterBlock.vue'
import SkuIdentityHeader from '@/modules/labs/components/SkuIdentityHeader.vue'
import SkuSearchSelect from '@/modules/labs/components/SkuSearchSelect.vue'
import StockComparePanel from '@/modules/labs/components/StockComparePanel.vue'
import {
  MARKED_WAREHOUSES,
  SIZE_ORDER,
  WINDOW,
  clusterTableProps,
  matrixView,
  pinnedSkus,
  product,
  skuList,
  stockCompare,
} from '@/modules/labs/fixtures'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'

const dateFrom = ref(WINDOW.start)
const dateTo = ref(WINDOW.end)
const selectedId = ref(product.nm_id)
const isPinned = ref(true)
const dirty = ref(true)
const refreshing = ref(false)
const allRefreshing = ref(false)

const skuLabel = computed(() => product.vendor_code)

/** Fake the round trip so the spinners and disabled states are visible. */
function fakeWork(flag) {
  flag.value = true
  setTimeout(() => {
    flag.value = false
  }, 1500)
}

/** The sandbox has no store to commit to; every handler is a sink. */
function noop() {}

const NO_SAVING_DAYS = new Set()

/**
 * The floating nav's targets. The copied components own their own <section>
 * markup and take no id prop, so the anchors are wrapper divs here rather than
 * an edit to any of them — the whole point of the sandbox is that those files
 * stay verbatim.
 */
const SECTIONS = [
  { id: 'ui-sec-matrix', label: 'По дням' },
  { id: 'ui-sec-stock', label: 'Остатки' },
  { id: 'ui-sec-chart', label: 'График' },
  { id: 'ui-sec-clusters', label: 'Кластеры' },
]
</script>

<template>
  <!-- Below is `MonitoringView.vue`'s own template, block for block. -->
  <div class="app-container ui-wrap">
    <div class="w-full">
      <h1 class="sr-only">Мониторинг SKU — дизайн-песочница</h1>

      <!-- Sticky, so the glass has the page scrolling underneath it. -->
      <div class="ui-bar ui-glass flex flex-wrap items-start justify-between gap-sm">
        <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" @apply="noop" />
        <RefreshAllSkusButton
          :refreshing="allRefreshing"
          :error="null"
          :warning="null"
          @refresh="fakeWork(allRefreshing)"
        />
      </div>

      <SkuSearchSelect
        :items="skuList"
        :loading="false"
        :selected-id="selectedId"
        @select="selectedId = $event"
        @apply="noop"
      />

      <PinnedSkuRow
        :items="pinnedSkus"
        :selected-id="selectedId"
        @select="selectedId = $event.nm_id"
        @reorder="noop"
      />

      <SkuIdentityHeader
        :product="product"
        :sku-label="skuLabel"
        :is-pinned="isPinned"
        @toggle-pin="isPinned = !isPinned"
      />

      <section id="ui-sec-matrix" class="mt-lg" aria-label="Ежедневные метрики">
        <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

        <!-- The block band's own light source. Unlike the ambient orbs on
                 `.ui-ground`, these are NOT fixed: they are absolutely placed
                 inside this section, at the band's own position, and scroll
                 with it. That is what makes the tiles' transparency legible —
                 a pane over a flat ground shows nothing, a pane over a colour
                 edge shows everything. -->
        <div class="ui-matrix-frame">
          <UiBlockOrbs />

          <MetricsTable
            class="mt-sm"
            :days="matrixView.days"
            :rows="matrixView.rows"
            :price-rows="matrixView.priceRows"
            :stock-rows="matrixView.stockRows"
            :stock-total-rows="matrixView.stockTotalRows"
            :comments="product.comments"
            :comment-saving-days="NO_SAVING_DAYS"
            :day-actions="product.day_actions"
            :action-saving-days="NO_SAVING_DAYS"
            :editing-disabled="false"
            @edit="noop"
            @comment="noop"
            @action="noop"
          />
        </div>

        <MatrixEditToolbar
          :dirty="dirty"
          :saving="false"
          :refreshing="refreshing"
          :loading="false"
          :error="null"
          :warning="null"
          @save="dirty = false"
          @refresh="fakeWork(refreshing)"
        />
      </section>

      <div id="ui-sec-stock">
        <StockComparePanel
          :sides="stockCompare"
          :marked-warehouses="MARKED_WAREHOUSES"
          :size-order="SIZE_ORDER"
          :max-date="WINDOW.end"
          @change-day="noop"
          @toggle-mark="noop"
        />
      </div>

      <div id="ui-sec-chart"><MetricsChart :view="matrixView" /></div>

      <div id="ui-sec-clusters"><SkuClusterBlock v-bind="clusterTableProps" /></div>
    </div>
  </div>

  <SectionNav :sections="SECTIONS" />
</template>

<style scoped src="@/modules/labs/views/LabMonitoringView.css"></style>
