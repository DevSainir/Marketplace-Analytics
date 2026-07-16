<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { isoDaysAgo } from '@/core/utils/dates'

import DayPicker from '@/modules/monitoring/components/DayPicker.vue'
import MetricsTable from '@/modules/monitoring/components/MetricsTable.vue'
import PeriodSelector from '@/modules/monitoring/components/PeriodSelector.vue'
import PinnedSkuRow from '@/modules/monitoring/components/PinnedSkuRow.vue'
import SkuSearchSelect from '@/modules/monitoring/components/SkuSearchSelect.vue'
import StockBreakdownTable from '@/modules/monitoring/components/StockBreakdownTable.vue'
import StockSizesPanel from '@/modules/monitoring/components/StockSizesPanel.vue'
import { useMonitoringStore } from '@/modules/monitoring/store'

const store = useMonitoringStore()
const route = useRoute()
const router = useRouter()

// Default inclusive window: the last 30 days INCLUDING today — the funnel has
// no current-day data yet (blank cells), but today's price/stock snapshots
// must already show.
const DEFAULT_FROM = isoDaysAgo(30)
const DEFAULT_TO = isoDaysAgo(0)

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

// --- global pinned SKUs («Закрепить») -------------------------------------
const isPinned = computed(() => product.value != null && store.pinnedIds.has(product.value.nm_id))

function togglePin() {
  if (!product.value) return
  store.toggleSkuPin(product.value.nm_id, product.value.vendor_code ?? null)
}

// --- per-SKU comment («Комментарий») --------------------------------------
// A free-text note saved on the SKU (global, shared by everyone). The draft is
// local; it re-seeds whenever the analyzed SKU (or its persisted note) changes.
const commentDraft = ref(product.value?.comment ?? '')
watch(
  () => [product.value?.nm_id, product.value?.comment],
  () => {
    commentDraft.value = product.value?.comment ?? ''
  },
)

/** True while the draft differs from the persisted note (enables «Сохранить»). */
const commentDirty = computed(() => commentDraft.value.trim() !== (product.value?.comment ?? ''))

function saveComment() {
  if (!commentDirty.value) return
  store.saveComment(commentDraft.value)
}

// --- two-day stock comparison ----------------------------------------------
// Both side-by-side tables render the UNION of the two days' sizes so their
// rows align 1:1 (a size absent on one day shows blank there).
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

onMounted(() => {
  window.addEventListener('keydown', handleHistoryKey)
  store.fetchPins()
})
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

      <!-- Ambiguous vendor-code deep link: let the user pick the exact SKU -->
      <section
        v-if="store.lookupMatches.length"
        class="mt-lg rounded-card bg-surface p-md shadow-card"
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
               action accent; title small grey; the pin toggle at the right. -->
          <h2 class="text-h2 font-bold text-primary">{{ product.vendor_code ?? skuLabel }}</h2>
          <span class="text-tiny font-semibold text-action">SKU {{ product.nm_id }}</span>
          <span v-if="product.title" class="text-tiny text-muted">{{ product.title }}</span>
          <button
            type="button"
            class="ml-auto inline-flex items-center gap-xs self-center rounded-btn px-sm py-xs text-tiny font-semibold shadow-soft transition"
            :class="
              isPinned
                ? 'bg-action/10 text-action hover:bg-action/20'
                : 'bg-surface text-primary hover:bg-surface-hover'
            "
            @click="togglePin"
          >
            <svg
              class="h-3.5 w-3.5 flex-none"
              viewBox="0 0 24 24"
              :fill="isPinned ? 'currentColor' : 'none'"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            >
              <path
                d="M16 3a1 1 0 0 1 .95 1.32L15.6 8.4l3.3 3.3a1 1 0 0 1-.4 1.66l-4.75 1.58-1.04 5.2a1 1 0 0 1-1.69.51L7.3 16.93l-3.6 3.6a.75.75 0 0 1-1.06-1.06l3.6-3.6-3.72-3.72a1 1 0 0 1 .51-1.69l5.2-1.04L9.8 4.67A1 1 0 0 1 11.46 4.27l3.3 3.3 4.08-1.36A1 1 0 0 1 16 3Z"
              />
            </svg>
            {{ isPinned ? 'Закреплено' : 'Закрепить' }}
          </button>
        </div>

        <section class="mt-lg" aria-label="Ежедневные метрики">
          <h2 class="text-h3 font-semibold text-primary">Метрики по дням</h2>

          <MetricsTable
            class="mt-sm"
            :days="metricsMatrix.days"
            :rows="metricsMatrix.rows"
            :price-rows="metricsMatrix.priceRows"
            :stock-rows="metricsMatrix.stockRows"
            :stock-total-rows="metricsMatrix.stockTotalRows"
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
              <span v-if="store.matrixDirty" class="text-base font-bold text-status-warning">
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

          <p v-if="store.matrixEditError" class="mt-xs text-tiny text-status-negative" role="alert">
            {{ store.matrixEditError }}
          </p>
        </section>

        <!-- Per-SKU comment: a compact, wide note card under the daily table.
             The note is saved on the SKU (shared by everyone). -->
        <section class="comment-card mt-md" aria-label="Комментарий">
          <div class="rounded-card bg-surface px-md py-sm shadow-card">
            <div class="flex items-center gap-xs">
              <svg
                class="h-3.5 w-3.5 flex-none text-action"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2Z" />
              </svg>
              <h3 class="text-micro font-semibold uppercase tracking-wide text-muted">
                Комментарий
              </h3>
            </div>
            <div class="mt-xs flex items-end gap-sm">
              <textarea
                v-model="commentDraft"
                rows="2"
                maxlength="2000"
                placeholder="Заметка по этому SKU — видна всей команде. Ctrl+Enter — сохранить."
                class="min-w-0 flex-1 resize-y rounded-btn border border-border-subtle bg-canvas px-sm py-xs text-base leading-snug text-primary shadow-soft transition placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/30"
                @keydown.enter.ctrl.prevent="saveComment"
                @keydown.enter.meta.prevent="saveComment"
              ></textarea>
              <button
                type="button"
                :disabled="!commentDirty || store.commentSaving"
                class="inline-flex h-9 flex-none items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-surface-hover disabled:cursor-not-allowed disabled:text-muted disabled:opacity-60"
                @click="saveComment"
              >
                {{ store.commentSaving ? 'Сохраняем…' : 'Сохранить' }}
              </button>
            </div>
          </div>
        </section>

        <!-- Warehouses × sizes stock: TWO snapshot days side by side for
             visual dynamics (right = today, left = yesterday by default);
             each side has its own day picker, rows (sizes) are shared. -->
        <section v-if="product.stock" class="mt-lg" aria-label="Остатки по складам">
          <h2 class="text-h3 font-semibold text-primary">Остатки по складам</h2>
          <div class="mt-sm flex gap-md">
            <!-- ONE shared sizes panel for both day tables (rows align 1:1). -->
            <div v-if="sharedStockSizes.length" class="w-28 flex-none">
              <div class="mb-xs h-8" aria-hidden="true"></div>
              <StockSizesPanel :sizes="sharedStockSizes" />
            </div>
            <div v-for="side in ['left', 'right']" :key="side" class="min-w-0 flex-1">
              <DayPicker
                class="mb-xs"
                :model-value="store.stockCompare[side].date"
                :max="DEFAULT_TO"
                :aria-label="side === 'left' ? 'День левой таблицы' : 'День правой таблицы'"
                @update:model-value="onStockDayChange(side, $event)"
              />
              <StockBreakdownTable
                :class="store.stockCompare[side].loading ? 'opacity-60' : ''"
                :cells="store.stockCompare[side].stock?.cells ?? []"
                :marked-warehouses="store.markedWarehouses"
                :size-order="sharedStockSizes"
                hide-size-column
                empty-message="Нет снимка остатков за выбранный день."
                @toggle-mark="store.toggleWarehouseMark"
              />
            </div>
          </div>
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
