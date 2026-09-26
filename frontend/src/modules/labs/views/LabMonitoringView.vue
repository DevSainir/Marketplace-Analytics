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
import PinnedSkuRow from '@/modules/labs/components/PinnedSkuRow.vue'
import RefreshAllSkusButton from '@/modules/labs/components/RefreshAllSkusButton.vue'
import SkuIdentityHeader from '@/modules/labs/components/SkuIdentityHeader.vue'
import SkuSearchSelect from '@/modules/labs/components/SkuSearchSelect.vue'
import StockComparePanel from '@/modules/labs/components/StockComparePanel.vue'
import { longMatrixView } from '@/modules/labs/longWindow'
import { unionStockSizes } from '@/modules/labs/stockCompareSizes'
import {
  DEFAULT_NM_ID,
  WINDOW,
  // clusterTableProps,  // dormant — see the «Рекламные кластеры» note below
  matrixViewFor,
  pinnedSkus,
  products,
  skuList,
} from '@/modules/labs/fixtures'

import '@/core/styles/ui-next/tokens.css'
import '@/core/styles/ui-next/components.css'
import '@/core/styles/ui-next/skin.css'

const dateFrom = ref(WINDOW.start)
const dateTo = ref(WINDOW.end)
const selectedId = ref(DEFAULT_NM_ID)

/** A made-up SKU with no fixture of its own falls back to the first card. */
const product = computed(() => products[selectedId.value] ?? products[DEFAULT_NM_ID])
const matrixView = computed(() => matrixViewFor(product.value))
const stockSizes = computed(() => unionStockSizes(product.value.stock_days))
const isPinned = ref(true)
const dirty = ref(true)
const refreshing = ref(false)
const allRefreshing = ref(false)

const skuLabel = computed(() => product.value.vendor_code)

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
  { id: 'ui-sec-year', label: 'Год' },
  // `ui-sec-clusters` («Кластеры») belongs here when the block comes back.
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
          :campaign-ids="product.campaign_ids"
          :nm-id="product.nm_id"
          @edit="noop"
          @comment="noop"
          @action="noop"
        />

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
        <StockComparePanel :days="product.stock_days" :size-order="stockSizes" />
      </div>

      <div id="ui-sec-chart"><MetricsChart :view="matrixView" /></div>

      <!-- The SAME chart component, handed a YEAR of days (`longWindow.js`)
           instead of the ten the rest of the sandbox runs on. Nothing about it
           is long-window-specific any more — that is the thing worth being able
           to look at, and at ten days it cannot be seen. -->
      <div id="ui-sec-year" class="mt-2xl border-t border-border-subtle pt-lg">
        <h2 class="text-h2 font-semibold text-primary">Тот же график на годе</h2>
        <p class="mt-xs max-w-3xl text-base text-muted">
          Год целиком, без горизонтальной прокрутки: всё линиями, точка на каждый день, по неделям
          разбита только ось — вертикаль и дата на каждом понедельнике.
        </p>
        <MetricsChart :view="longMatrixView" :default-metrics="['carts', 'orders']" />
      </div>

      <!-- «Рекламные кластеры» — DORMANT here too, so this sandbox stays a
           faithful mirror of MonitoringView.vue, which stopped rendering it on
           2026-09-09. Not dead code. Restore alongside the real page with:
           <div id="ui-sec-clusters"><SkuClusterBlock v-bind="clusterTableProps" /></div> -->
    </div>
  </div>

  <SectionNav :sections="SECTIONS" />
</template>

<style scoped src="@/modules/labs/views/LabMonitoringView.css"></style>
