<script setup>
/**
 * DESIGN SANDBOX — /monitoring on a second design system.
 *
 * The components under `labs/components/` are VERBATIM copies of the
 * monitoring ones: same markup, same props, same behaviour, only their import
 * paths rewritten. This view composes them in the same order
 * `MonitoringView.vue` does, on the same live data (`labs/store.js`), through
 * the copied `buildMetricsMatrix`.
 *
 * Nothing structural is re-implemented here, so every difference you can see
 * between the two pages comes from one stylesheet — `skin.css`, which
 * re-points the design tokens the copied markup already asks for. The editing
 * controls are sinks: the sandbox is for looking.
 */
import { computed, onMounted } from 'vue'

import DataState from '@/core/components/DataState.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import MatrixEditToolbar from '@/modules/labs/components/MatrixEditToolbar.vue'
import MetricsChart from '@/modules/labs/components/MetricsChart.vue'
import MetricsTable from '@/modules/labs/components/MetricsTable.vue'
import SectionNav from '@/core/components/SectionNav.vue'
import PinnedSkuRow from '@/modules/labs/components/PinnedSkuRow.vue'
import RefreshAllSkusButton from '@/modules/labs/components/RefreshAllSkusButton.vue'
import SkuIdentityHeader from '@/modules/labs/components/SkuIdentityHeader.vue'
import SkuSearchSelect from '@/modules/labs/components/SkuSearchSelect.vue'
import StockComparePanel from '@/modules/labs/components/StockComparePanel.vue'
import StockDesignLab from '@/modules/labs/components/StockDesignLab.vue'
import { campaignIdsByDay } from '@/modules/labs/campaignLinks'
import { buildMetricsMatrix } from '@/modules/labs/metricsMatrix'
import { useLabMonitoringStore } from '@/modules/labs/store'
import { unionStockSizes } from '@/modules/labs/stockCompareSizes'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'

const store = useLabMonitoringStore()

const product = computed(() => store.product)
const matrixView = computed(() =>
  buildMetricsMatrix(store.product, store.product?.price_currency ?? ''),
)
const longMatrixView = computed(() =>
  buildMetricsMatrix(store.longProduct, store.longProduct?.price_currency ?? ''),
)
const campaigns = computed(() => ({
  nmId: store.product?.nm_id,
  byDay: campaignIdsByDay(store.product?.matrix_base),
}))
const stockSizes = computed(() => unionStockSizes(store.stockDays))
const isPinned = computed(() => store.pinnedSkus.some((pin) => pin.nm_id === store.selectedId))
const skuLabel = computed(() => store.product?.vendor_code ?? '')

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
  { id: 'ui-sec-stock-next', label: 'Остатки · новые' },
  { id: 'ui-sec-chart', label: 'График' },
  { id: 'ui-sec-year', label: 'Год' },
  // `ui-sec-clusters` («Кластеры») belongs here when the block comes back.
]
onMounted(() => store.init())
</script>

<template>
  <!-- Below is `MonitoringView.vue`'s own template, block for block. -->
  <div class="app-container ui-wrap">
    <div class="w-full">
      <h1 class="sr-only">Мониторинг SKU — дизайн-песочница</h1>

      <!-- Sticky, so the glass has the page scrolling underneath it. -->
      <div class="ui-bar ui-glass flex flex-wrap items-start justify-between gap-sm">
        <PeriodSelector :from="store.dateFrom" :to="store.dateTo" @range="store.setPeriod" />
        <RefreshAllSkusButton :refreshing="false" :error="null" :warning="null" @refresh="noop" />
      </div>

      <SkuSearchSelect
        :items="store.skuList"
        :loading="store.loading"
        :selected-id="store.selectedId"
        @select="store.select"
        @apply="noop"
      />

      <PinnedSkuRow
        :items="store.pinnedSkus"
        :selected-id="store.selectedId"
        @select="store.select($event.nm_id)"
        @reorder="noop"
      />

      <DataState v-if="store.error" kind="error" layout="line" :text="store.error" class="mt-lg" />
      <template v-if="product">
        <SkuIdentityHeader
          :product="product"
          :sku-label="skuLabel"
          :is-pinned="isPinned"
          @toggle-pin="noop"
        />

        <section id="ui-sec-matrix" class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable
            class="mt-sm"
            :days="matrixView.days"
            :rows="matrixView.rows"
            :price-rows="matrixView.priceRows"
            :stock-rows="matrixView.stockRows"
            :stock-total-rows="matrixView.stockTotalRows"
            :comments="product.comments ?? {}"
            :comment-saving-days="NO_SAVING_DAYS"
            :day-actions="product.day_actions ?? {}"
            :action-saving-days="NO_SAVING_DAYS"
            :editing-disabled="false"
            :campaigns="campaigns"
            @edit="noop"
            @comment="noop"
            @action="noop"
          />

          <MatrixEditToolbar
            :dirty="false"
            :saving="false"
            :refreshing="false"
            :loading="store.loading"
            :error="null"
            :warning="null"
            @save="noop"
            @refresh="noop"
          />
        </section>

        <div id="ui-sec-stock">
          <StockComparePanel :days="store.stockDays" :size-order="stockSizes" />
        </div>

        <!-- LAB-ONLY: three candidate redesigns of the grid above, on the same
           days, so the four can be compared without switching pages. -->
        <div id="ui-sec-stock-next">
          <StockDesignLab :days="store.stockDays" :size-order="stockSizes" />
        </div>

        <div id="ui-sec-chart"><MetricsChart :view="matrixView" /></div>

        <!-- The SAME chart component, handed a YEAR of the same SKU's days
           instead of the window above. Nothing about it is
           long-window-specific any more — that is the thing worth being able
           to look at, and at thirty days it cannot be seen. -->
        <div id="ui-sec-year" class="mt-2xl border-t border-border-subtle pt-lg">
          <h2 class="text-h2 font-semibold text-primary">Тот же график на годе</h2>
          <p class="mt-xs max-w-3xl text-base text-muted">
            Год целиком, без горизонтальной прокрутки: всё линиями, точка на каждый день, по неделям
            разбита только ось — вертикаль и дата на каждом понедельнике.
          </p>
          <MetricsChart :view="longMatrixView" :default-metrics="['carts', 'orders']" />
        </div>
      </template>

      <!-- «Рекламные кластеры» — DORMANT here too, so this sandbox stays a
           faithful mirror of MonitoringView.vue, which stopped rendering it on
           2026-09-09. Not dead code. Restore alongside the real page with:
           <div id="ui-sec-clusters"><SkuClusterBlock v-bind="clusterTableProps" /></div> -->
    </div>
  </div>

  <SectionNav :sections="SECTIONS" />
</template>

<style scoped src="@/modules/labs/views/LabMonitoringView.css"></style>
