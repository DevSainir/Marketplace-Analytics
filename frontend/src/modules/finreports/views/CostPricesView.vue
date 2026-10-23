<script setup>
/**
 * The cost-price editor — the only place a human types a number into this module.
 *
 * Everything else in finreports is harvested from Wildberries and read-only;
 * cost of goods is the one P&L input WB does not know. The page states the
 * coverage plainly at the top, because the margin on the dashboard is only as
 * meaningful as the share of sold units these figures cover.
 */
import { computed, onMounted, ref } from 'vue'

import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import { formatNumber, formatPercent } from '@/core/utils/format'
import CostPriceExcelPanel from '@/modules/finreports/components/CostPriceExcelPanel.vue'
import CostPriceGrid from '@/modules/finreports/components/CostPriceGrid.vue'
import { useFinReportsStore } from '@/modules/finreports/store'

const store = useFinReportsStore()

/** The last import summary, shown in the Excel panel until the next upload. */
const importResult = ref(null)

const items = computed(() => store.costPrices?.items ?? [])
const missing = computed(() => store.costPrices?.missing ?? [])
const currency = computed(() => store.costPrices?.currency || 'KGS')

/** Coverage over the SKUs that actually sold in the last year. */
/**
 * Coverage over the SKUs that actually sold in the window.
 *
 * `costedSkus` counts only those with settled units, so it will read lower than
 * the number of rows carrying a cost in the grid below — nine costs on file, three
 * of them for SKUs that have ever sold. That gap is stated in the caption rather
 * than left for the reader to notice and mistrust.
 */
const coverage = computed(() => {
  const selling = items.value.filter((i) => i.sold_units > 0)
  const costedUnits = selling.reduce((sum, i) => sum + i.sold_units, 0)
  const missingUnits = missing.value.reduce((sum, i) => sum + (i.sold_units || 0), 0)
  const totalUnits = costedUnits + missingUnits
  return {
    costedSkus: selling.length,
    storedSkus: items.value.length,
    missingSkus: missing.value.length,
    costedUnits,
    totalUnits,
    pct: totalUnits ? (costedUnits / totalUnits) * 100 : null,
  }
})

/**
 * Apply the grid's pending edits: written costs and cleared ones.
 *
 * Clears go first so a save that fails leaves the removals visible rather than
 * half-applying in the order the rows happened to be listed.
 */
async function onSave({ save, clear }) {
  try {
    for (const nmId of clear) {
      await store.removeCostPrice(nmId)
    }
    if (save.length) await store.persistCostPrices(save)
  } catch {
    // The store surfaces the message; nothing to add here.
  }
}

async function onRemove(nmId) {
  try {
    await store.removeCostPrice(nmId)
  } catch {
    // Same.
  }
}

/** Which Excel action is running, so its own button says so. */
const exporting = ref(false)
const importing = ref(false)

/** Download the grid as an XLSX for offline editing. */
async function onExport() {
  exporting.value = true
  try {
    const { blob, filename } = await store.exportCostPrices()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch {
    // The store surfaces the message via costsError.
  } finally {
    exporting.value = false
  }
}

/** Apply a filled-in workbook and keep its summary on screen. */
async function onImport(file) {
  importing.value = true
  try {
    importResult.value = await store.importCostPrices(file)
  } catch {
    importResult.value = null
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  if (!store.costPrices) store.loadCostPrices()
})
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <div class="app-container py-lg">
    <PageHeader title="Cost price" :back="{ to: { name: 'finreports' }, label: 'Back to P&L' }" />

    <section
      v-if="coverage.totalUnits"
      class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <div class="flex flex-wrap items-baseline gap-lg phone:gap-sm">
        <div>
          <div class="text-tiny font-medium uppercase tracking-wide text-muted">
            Units sold with a cost price
          </div>
          <div
            class="mt-xs text-h2 font-bold tabular-nums"
            :class="coverage.pct >= 90 ? 'text-status-positive' : 'text-status-warning'"
          >
            {{ coverage.pct === null ? '—' : formatPercent(coverage.pct) }}
          </div>
        </div>
        <p class="max-w-2xl text-base text-muted">
          {{ formatNumber(coverage.costedUnits) }} of {{ formatNumber(coverage.totalUnits) }} units
          in the last year. Cost price set for {{ coverage.costedSkus }} of
          {{ coverage.costedSkus + coverage.missingSkus }} SKUs sold.
        </p>
      </div>
    </section>

    <CostPriceExcelPanel
      :busy="store.costsSaving"
      :exporting="exporting"
      :importing="importing"
      :result="importResult"
      :currency="currency"
      @export="onExport"
      @import="onImport"
    />

    <DataState v-if="!store.costPrices && store.costsLoading" kind="loading" />
    <DataState
      v-else-if="!store.costPrices && store.costsError"
      kind="error"
      :text="store.costsError"
    />

    <template v-else-if="store.costPrices">
      <DataState
        v-if="store.costsError"
        kind="error"
        layout="line"
        :text="store.costsError"
        class="mb-md"
      />
      <BusyRegion :busy="store.costsLoading">
        <CostPriceGrid
          :items="items"
          :missing="missing"
          :currency="currency"
          :saving="store.costsSaving"
          @save="onSave"
          @remove="onRemove"
        />
      </BusyRegion>
    </template>
  </div>
</template>
