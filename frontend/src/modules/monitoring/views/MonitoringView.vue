<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isoDaysAgo } from '@/core/utils/dates'

import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import PeriodSelector from '@/modules/monitoring/components/PeriodSelector.vue'
import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'
import { useMonitoringStore } from '@/modules/monitoring/store'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Default inclusive window: the last 30 full days, current day excluded.
const DEFAULT_FROM = isoDaysAgo(30)
const DEFAULT_TO = isoDaysAgo(1)

/** Pick the search-relevant params out of a route query (arrays/absent → defaults). */
function readSearchQuery(query) {
  const pick = (key) => (typeof query[key] === 'string' ? query[key] : '')
  return {
    sku: pick('sku'),
    date_from: pick('date_from') || DEFAULT_FROM,
    date_to: pick('date_to') || DEFAULT_TO,
  }
}

// Draft period: edited freely, takes effect on «Применить» or on picking a SKU.
const initial = readSearchQuery(route.query)
const dateFrom = ref(initial.date_from)
const dateTo = ref(initial.date_to)

// The URL is the single source of truth (deep-linkable, survives refresh and
// back/forward): handlers only push a new query, this watcher does ALL
// fetching — the SKU list follows the window, the detail follows sku + window.
watch(
  () => route.query,
  (query, oldQuery) => {
    if (route.name !== 'monitoring') return // navigating away, not a new search
    const search = readSearchQuery(query)
    const old = oldQuery ? readSearchQuery(oldQuery) : null

    // Back/forward must also rewind the period selector.
    dateFrom.value = search.date_from
    dateTo.value = search.date_to

    if (!old || old.date_from !== search.date_from || old.date_to !== search.date_to) {
      store.fetchSkuList({ date_from: search.date_from, date_to: search.date_to })
    }

    if (!search.sku) {
      store.reset()
      return
    }
    if (old && JSON.stringify(search) === JSON.stringify(old)) return
    store.fetchProductData(search.sku, { date_from: search.date_from, date_to: search.date_to })
  },
  { immediate: true },
)

/** Dropdown pick: analyze this SKU over the drafted window. */
function handleSelect(item) {
  pushSearch(String(item.nm_id))
}

/**
 * «Применить»: apply the drafted period. A raw nm ID in the input is treated
 * as a direct pick; otherwise the currently analyzed SKU (if any) is kept.
 */
function handleApply(query) {
  const sku = /^\d+$/.test(query) ? query : readSearchQuery(route.query).sku
  pushSearch(sku)
}

// `push` (not `replace`) keeps every search reachable via the Back button.
function pushSearch(sku) {
  router.push({
    query: { ...(sku && { sku }), date_from: dateFrom.value, date_to: dateTo.value },
  })
}

const product = computed(() => store.currentProduct)

// Vendor code (артикул продавца) once the backend serves it; nm ID meanwhile.
const skuLabel = computed(() => product.value?.vendor_code ?? `SKU ${product.value?.nm_id ?? ''}`)

const windowLabel = computed(() => {
  const window = product.value?.window
  return window ? `${window.start} → ${window.end}` : ''
})

// Metric rows × day columns for the daily table (workbook replica). The store
// owns this reactive structure and patches cells in place on edit/undo/redo so
// the table doesn't fully re-render.
const metricsMatrix = computed(() => store.matrixView)

/** «Обновить»: re-fetch the current search with the same window. */
function refresh() {
  store.refreshFromWb()
}

// Editing is locked while a save or WB refresh is in flight.
const editingLocked = computed(() => store.matrixSaving || store.matrixRefreshing)

/** A cell edit: hand the raw value to the store (backend recomputes dependents). */
function handleCellEdit(edit) {
  store.applyCellEdit(edit)
}

// History keys: Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z (or Ctrl/Cmd+Y) redoes.
// Ignored while typing in an input and while a save/refresh is running.
function handleHistoryKey(event) {
  if (!(event.ctrlKey || event.metaKey)) return
  const key = event.key.toLowerCase()
  const isUndo = key === 'z' && !event.shiftKey
  const isRedo = (key === 'z' && event.shiftKey) || key === 'y'
  if (!isUndo && !isRedo) return
  const tag = event.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  if (editingLocked.value) return
  // Always swallow the undo/redo combo while the table is focused — otherwise a
  // second Ctrl+Z with an empty history falls through to the browser's own undo,
  // which moves focus into the search input.
  event.preventDefault()
  if (isRedo && store.canRedoMatrix) {
    store.redoMatrixEdit()
  } else if (isUndo && store.canUndoMatrix) {
    store.undoMatrixEdit()
  }
}

onMounted(() => window.addEventListener('keydown', handleHistoryKey))
onBeforeUnmount(() => window.removeEventListener('keydown', handleHistoryKey))
</script>

<template>
  <!-- Canvas: the old max-w-7xl (80rem) plus 2/3 of the spare viewport width
       beyond it — calc(80rem + (100vw - 80rem) * 2/3). Below 80rem viewports
       the calc exceeds 100vw, so w-full keeps behaving as before. -->
  <div class="mx-auto w-full max-w-[calc(26.667rem_+_66.667vw)] px-md py-lg sm:px-lg">
    <div class="w-full">
      <h1 class="sr-only">Мониторинг SKU</h1>

      <!-- Period selector, slightly above the search bar -->
      <PeriodSelector v-model:from="dateFrom" v-model:to="dateTo" class="mb-sm" />

      <!-- Search bar: apply on the left, dropdown with all SKUs below -->
      <SkuSearchSelect
        :items="store.skuList"
        :loading="store.skuListLoading"
        :selected-id="product?.nm_id ?? null"
        @select="handleSelect"
        @apply="handleApply"
      />

      <p v-if="store.skuListError" class="mt-sm text-tiny text-status-negative">
        Не удалось загрузить список SKU: {{ store.skuListError }}
      </p>

      <!-- Ambiguous vendor-code deep link: let the user pick the exact SKU -->
      <section
        v-if="store.lookupMatches.length"
        class="mt-lg rounded-card bg-surface/75 p-md shadow-card backdrop-blur-md"
      >
        <p class="text-base font-medium text-primary">
          Найдено артикулов: {{ store.lookupMatches.length }} — выберите нужный:
        </p>
        <div class="mt-sm flex flex-wrap gap-sm">
          <button
            v-for="match in store.lookupMatches"
            :key="match.nm_id"
            type="button"
            class="inline-flex max-w-full items-center gap-sm rounded-btn border border-border-subtle bg-surface px-sm py-xs text-base shadow-soft transition hover:border-action hover:bg-action/10"
            @click="handleSelect(match)"
          >
            <span class="font-semibold text-primary">{{ match.vendor_code }}</span>
            <span class="truncate text-tiny text-muted">{{ match.title }}</span>
          </button>
        </div>
      </section>

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
        <div class="mt-lg flex flex-wrap items-baseline gap-x-sm gap-y-xs">
          <!-- Vendor code is the big black heading; the nm ID follows in the
               action accent; title small grey; the window label at the right. -->
          <h2 class="text-h2 font-bold text-primary">{{ product.vendor_code ?? skuLabel }}</h2>
          <span class="text-tiny font-semibold text-action">SKU {{ product.nm_id }}</span>
          <span v-if="product.title" class="text-tiny text-muted">{{ product.title }}</span>
          <span class="ml-auto text-tiny font-medium text-muted">{{ windowLabel }}</span>
        </div>

        <section class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable
            class="mt-sm"
            :days="metricsMatrix.days"
            :rows="metricsMatrix.rows"
            :price-rows="metricsMatrix.priceRows"
            :stock-rows="metricsMatrix.stockRows"
            :editing-disabled="editingLocked"
            @edit="handleCellEdit"
          />

          <!-- Hint on the left, actions on the right. The dirty caption sits
               UNDER the buttons so its appearance moves nothing. -->
          <div class="mt-sm flex flex-wrap items-start gap-md">
            <p class="min-w-0 text-tiny text-muted">
              Кликните по значению, чтобы изменить его — зависимые ячейки пересчитаются.
              <kbd class="rounded border border-border-subtle px-1">Ctrl</kbd>+<kbd
                class="rounded border border-border-subtle px-1"
                >Z</kbd
              >
              — отменить,
              <kbd class="rounded border border-border-subtle px-1">Ctrl</kbd>+<kbd
                class="rounded border border-border-subtle px-1"
                >Shift</kbd
              >+<kbd class="rounded border border-border-subtle px-1">Z</kbd> — повторить.
            </p>

            <div class="ml-auto flex items-center gap-sm">
              <span
                v-if="store.matrixDirty"
                class="text-base font-bold text-status-warning"
              >
                Есть несохранённые изменения
              </span>
              <button
                type="button"
                :disabled="!store.matrixDirty || store.matrixSaving || store.matrixRefreshing"
                class="inline-flex h-9 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-surface-hover disabled:cursor-not-allowed disabled:text-muted disabled:opacity-60"
                @click="store.saveMatrixEdits()"
              >
                {{ store.matrixSaving ? 'Сохраняем…' : 'Сохранить' }}
              </button>
              <button
                type="button"
                :disabled="store.loading || store.matrixRefreshing || store.matrixSaving"
                class="inline-flex h-9 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60"
                @click="refresh"
              >
                {{ store.matrixRefreshing ? 'Обновляем из Wildberries…' : 'Обновить' }}
              </button>
            </div>
          </div>

          <p
            v-if="store.matrixEditError"
            class="mt-xs text-tiny text-status-negative"
            role="alert"
          >
            {{ store.matrixEditError }}
          </p>
        </section>
      </template>

      <!-- Initial state: an inviting hint until the first SKU is submitted -->
      <div v-else-if="!store.lookupMatches.length" class="mt-20 text-center">
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
