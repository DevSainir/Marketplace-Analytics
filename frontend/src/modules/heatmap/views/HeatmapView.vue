<script setup>
/**
 * «Тепловая карта» — /heatmap, and /labs/heatmap with `labs`: the same page
 * plus what is still being tried out there — «Норма: ручной ввод».
 *
 * Every article of the кабинет, day by day, painted by one metric: the view for
 * a кабинет with too many working articles to watch one at a time, where the
 * question is not «how is this card» but «which cards dipped, and when».
 *
 * The view composes; the store decides what costs a request. The previous grid
 * stays on screen, dimmed, while the next one loads — blanking it would turn
 * every filter click into a full rebuild of the page.
 */
import { computed, onMounted, ref, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import { useHistoryKeys } from '@/core/utils/historyKeys'
import { useMembersStore } from '@/modules/profile'

import HeatmapControls from '@/modules/heatmap/components/HeatmapControls.vue'
import HeatmapDayList from '@/modules/heatmap/components/HeatmapDayList.vue'
import HeatmapFilters from '@/modules/heatmap/components/HeatmapFilters.vue'
import HeatmapGroupDialog from '@/modules/heatmap/components/HeatmapGroupDialog.vue'
import HeatmapHelp from '@/modules/heatmap/components/HeatmapHelp.vue'
import HeatmapPager from '@/modules/heatmap/components/HeatmapPager.vue'
import HeatmapTable from '@/modules/heatmap/components/HeatmapTable.vue'
import '@/modules/heatmap/components/styles/heatmap.css'
import { metricOf } from '@/modules/heatmap/metrics'
import { useHeatmapNormsStore } from '@/modules/heatmap/normsStore'
import { useHeatmapStore } from '@/modules/heatmap/store'

const props = defineProps({
  /** The lab build: hand-set norms on. Their API refuses anyone but us. */
  labs: { type: Boolean, default: false },
})

const store = useHeatmapStore()
const norms = useHeatmapNormsStore()
const members = useMembersStore()

/** The settlement's money needs P&L on top of monitoring — see the API's check. */
const finance = computed(() => members.canReach('finreports'))

// A remembered money metric must not survive into a session without P&L.
watch(
  finance,
  (allowed) => {
    if (allowed) return
    if (metricOf(store.metric)?.settled) store.metric = 'orders'
    if (metricOf(store.metric2)?.settled) store.metric2 = null
  },
  { immediate: true },
)

/** The painted metric's norm per article, while norms are typed by hand. */
const normOf = computed(() =>
  store.manualNorms ? (nmId) => norms.normOf(nmId, store.primary.key) : null,
)

function saveNorm(nmId, value) {
  norms.save(nmId, store.primary.key, value)
}

const dialogOpen = ref(false)
const editing = ref(null)

/** The grid's currencies — prices, orders, advertising, settlement — in one object. */
const currencies = computed(() => ({
  prices: store.data?.price_currency ?? '',
  orders: store.data?.order_currency ?? '',
  ads: store.data?.ad_currencies ?? [],
  settlement: store.data?.currency ?? '',
}))

const settledNote = computed(() => {
  const data = store.data
  if (!data?.settled_to || !(store.primary?.settled || store.secondary?.settled)) return ''
  const [year, month, day] = data.settled_to.split('-')
  return `Финансы из отчётов WB — по ${day}.${month}.${year}; позже дни ещё не рассчитаны.`
})

function openGroup(group = null) {
  editing.value = group
  store.groupError = ''
  dialogOpen.value = true
}

async function saveGroup(group) {
  if (await store.saveGroup(group)) dialogOpen.value = false
}

async function deleteGroup(id) {
  if (await store.removeGroup(id)) dialogOpen.value = false
}

onMounted(() => store.init())

// Only while norms are typed — otherwise the page has nothing to undo, and the
// combo stays the browser's.
useHistoryKeys({
  undo: () => norms.undo(),
  redo: () => norms.redo(),
  locked: () => !store.manualNorms,
})

// Both routes render this one component, so a hop between them keeps the
// instance and only flips `labs`. The store outlives the route too: whichever
// way the hop goes, the norms start switched off.
// A norm belongs to an article: any other cut switches it off, and the
// picker greys «ручной ввод» out until the cut is «По товару» again.
watch(
  () => store.groupBy,
  (groupBy) => {
    if (groupBy !== 'sku') norms.mode = 'default'
  },
)

watch(
  () => props.labs,
  (labs, before) => {
    // The public page never paints hand-set norms; the lab keeps the mode it
    // had (remembered for a while — see `settingsMemory.js`) unless the reader
    // just came over from the public page.
    if (!labs || before === false) norms.mode = 'default'
    if (labs) norms.load().catch((err) => (norms.error = extractErrorMessage(err)))
  },
  { immediate: true },
)
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg flex flex-wrap items-center justify-between gap-md">
      <h1 class="text-h2 font-bold text-primary">Тепловая карта</h1>
      <HeatmapHelp :labs="labs" />
    </header>

    <HeatmapFilters
      v-model:subjects="store.subjects"
      v-model:group-ids="store.groupIds"
      v-model:nm-ids="store.nmIds"
      :date-from="store.dateFrom"
      :date-to="store.dateTo"
      :catalog="store.catalog"
      :groups="store.groups"
      @period="store.setPeriod"
      @add-group="openGroup()"
      @edit-group="openGroup"
    />

    <section class="rounded-card bg-surface p-lg shadow-card phone:p-md">
      <HeatmapControls
        v-model:metric="store.metric"
        v-model:metric2="store.metric2"
        v-model:period="store.period"
        v-model:group-by="store.groupBy"
        v-model:mode="store.mode"
        v-model:norm-mode="norms.mode"
        :norms="labs"
        :finance="finance"
        @swap="store.swapMetrics"
      />

      <p v-if="store.error" class="mb-md text-base text-status-negative">{{ store.error }}</p>
      <p v-if="norms.error" class="mb-md text-base text-status-negative">{{ norms.error }}</p>
      <p v-if="settledNote" class="mb-sm text-tiny text-muted">{{ settledNote }}</p>
      <p v-if="store.loading && !store.data" class="py-xl text-center text-base text-muted">
        Считаем…
      </p>

      <div v-if="store.data && store.primary" :class="{ 'hm-stale': store.loading }">
        <HeatmapTable
          class="hidden sm:block"
          :currencies="currencies"
          :columns="store.columns"
          :period="store.data.period"
          :rows="store.view.rows"
          :tints="store.tints"
          :totals="store.totals"
          :primary="store.primary"
          :secondary="store.secondary"
          :sort="store.sort"
          :group-by="store.data.group_by"
          :date-from="store.data.date_from"
          :date-to="store.data.date_to"
          :norm-of="normOf"
          @sort="store.toggleSort"
          @norm="saveNorm"
        />
        <HeatmapDayList
          class="sm:hidden"
          :currencies="currencies"
          :columns="store.columns"
          :period="store.data.period"
          :rows="store.view.rows"
          :tints="store.tints"
          :totals="store.totals"
          :primary="store.primary"
          :secondary="store.secondary"
          :norm-of="normOf"
          @norm="saveNorm"
        />
        <HeatmapPager
          v-model:page-size="store.pageSize"
          :page="store.view.page"
          :pages="store.view.pages"
          :total="store.sortedRows.length"
          @update:page="store.page = $event"
        />
      </div>
    </section>

    <!-- Under the card, like the monitoring matrix's edit hint. -->
    <p v-if="store.manualNorms" class="mt-sm text-tiny text-muted">
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

    <HeatmapGroupDialog
      :open="dialogOpen"
      :group="editing"
      :cards="store.catalog.items"
      :busy="store.groupBusy"
      :error="store.groupError"
      @close="dialogOpen = false"
      @save="saveGroup"
      @delete="deleteGroup"
    />
  </div>
</template>

<style scoped>
/* Dimmed and inert, never hidden — see the view's comment. */
.hm-stale {
  opacity: 0.45;
  pointer-events: none;
  transition: opacity 120ms ease-out;
}
</style>
