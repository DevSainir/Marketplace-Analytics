<script setup>
/**
 * The cost-price editor — the only place a human types a number into this module.
 *
 * Everything else in finreports is harvested from WildBerries and read-only;
 * cost of goods is the one P&L input WB does not know. The page states the
 * coverage plainly at the top, because the margin on the dashboard is only as
 * meaningful as the share of sold units these figures cover.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

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

/** Download the grid as an XLSX for offline editing. */
async function onExport() {
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
  }
}

/** Apply a filled-in workbook and keep its summary on screen. */
async function onImport(file) {
  try {
    importResult.value = await store.importCostPrices(file)
  } catch {
    importResult.value = null
  }
}

onMounted(() => {
  if (!store.costPrices) store.loadCostPrices()
})
</script>

<template>
  <!-- `.app-container` is the shared canvas width + safe-area gutter (main.css). -->
  <main class="app-container py-xl phone:py-lg">
    <header class="mb-lg">
      <RouterLink
        :to="{ name: 'finreports' }"
        class="text-base font-medium text-action hover:underline"
      >
        ← К отчёту о прибылях и убытках
      </RouterLink>
      <h1 class="mt-sm text-h2 font-bold text-primary">Себестоимость</h1>
      <p class="mt-xs max-w-3xl text-base text-muted">
        Единственная цифра в отчёте, которой нет у WB. Указывайте себестоимость 1 ед.
        <b>с фулфилментом</b>, в {{ currency }} — той же валюте, в которой WB рассчитывается. SKU
        без себестоимости не занижают отчёт молча: они исключаются из расчёта прибыли, а её покрытие
        показано и здесь, и на дашборде.
      </p>
    </header>

    <section
      v-if="coverage.totalUnits"
      class="mb-lg rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <div class="flex flex-wrap items-baseline gap-lg phone:gap-sm">
        <div>
          <div class="text-tiny font-medium uppercase tracking-wide text-muted">
            Покрытие проданных единиц
          </div>
          <div
            class="mt-xs text-h2 font-bold tabular-nums"
            :class="coverage.pct >= 90 ? 'text-status-positive' : 'text-status-warning'"
          >
            {{ coverage.pct === null ? '—' : formatPercent(coverage.pct) }}
          </div>
        </div>
        <p class="max-w-2xl text-base text-muted">
          {{ formatNumber(coverage.costedUnits) }} из {{ formatNumber(coverage.totalUnits) }} шт за
          последний год. Себестоимость задана для {{ coverage.costedSkus }} из
          {{ coverage.costedSkus + coverage.missingSkus }} продававшихся SKU, не задана для
          {{ coverage.missingSkus }}.
          <span v-if="coverage.storedSkus > coverage.costedSkus">
            Ещё {{ coverage.storedSkus - coverage.costedSkus }} себестоимостей заданы для SKU,
            которые за этот период не продавались — на отчёт они пока не влияют.
          </span>
        </p>
      </div>
    </section>

    <CostPriceExcelPanel
      :busy="store.costsSaving"
      :result="importResult"
      :currency="currency"
      @export="onExport"
      @import="onImport"
    />

    <div
      v-if="store.costsLoading"
      class="rounded-card border border-border-subtle bg-surface px-lg py-xl text-center text-base text-muted shadow-card"
    >
      Загрузка…
    </div>

    <template v-else>
      <p v-if="store.costsError" class="mb-md text-base text-status-negative">
        {{ store.costsError }}
      </p>
      <CostPriceGrid
        :items="items"
        :missing="missing"
        :currency="currency"
        :saving="store.costsSaving"
        @save="onSave"
        @remove="onRemove"
      />
    </template>
  </main>
</template>
