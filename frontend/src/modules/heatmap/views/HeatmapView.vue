<script setup>
/**
 * "Heatmap" — /heatmap.
 *
 * Every article of the workspace, day by day, painted by one metric: the view for
 * a workspace with too many working articles to watch one at a time, where the
 * question is not "how is this card" but "which cards dipped, and when".
 *
 * The view composes; the store decides what costs a request. The previous grid
 * stays on screen, dimmed, while the next one loads — blanking it would turn
 * every filter click into a full rebuild of the page.
 */
import { computed, onMounted, watch } from 'vue'

import { extractErrorMessage } from '@/core/api/axios'
import PageHeader from '@/core/components/PageHeader.vue'
import BusyRegion from '@/core/components/BusyRegion.vue'
import DataState from '@/core/components/DataState.vue'
import { formatDay } from '@/core/utils/calendarWords'
import { useHistoryKeys } from '@/core/utils/historyKeys'
import { BackfillNotice } from '@/modules/profile'

import HeatmapControls from '@/modules/heatmap/components/HeatmapControls.vue'
import HeatmapDayList from '@/modules/heatmap/components/HeatmapDayList.vue'
import HeatmapFilters from '@/modules/heatmap/components/HeatmapFilters.vue'
import HeatmapHelp from '@/modules/heatmap/components/HeatmapHelp.vue'
import HeatmapPager from '@/modules/heatmap/components/HeatmapPager.vue'
import HeatmapTable from '@/modules/heatmap/components/HeatmapTable.vue'
import '@/modules/heatmap/components/styles/heatmap.css'
import { useGroupsStore } from '@/modules/heatmap/groupsStore'
import { useHeatmapNormsStore } from '@/modules/heatmap/normsStore'
import { useHeatmapStore } from '@/modules/heatmap/store'

const store = useHeatmapStore()
const norms = useHeatmapNormsStore()

/** The painted metric's norm per article, while norms are typed by hand. */
const normOf = computed(() =>
  store.manualNorms ? (nmId) => norms.normOf(nmId, store.primary.key) : null,
)

function saveNorm(nmId, value) {
  norms.save(nmId, store.primary.key, value)
}

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
  return `Finance from WB reports, up to ${formatDay(data.settled_to)}. Later days are not settled yet.`
})

// A group edited here changes the grid when the grid is cut or filtered by
// groups. A deleted chosen group leaves `groupIds` through `GroupsFilter`,
// which reloads by itself. Edits on other pages need nothing: `init` asks again
// on every visit.
const groups = useGroupsStore()
watch(
  () => groups.revision,
  () => {
    if (store.groupBy === 'group' || store.groupIds.length) store.load()
  },
)

onMounted(() => store.init())

// Only while norms are typed — otherwise the page has nothing to undo, and the
// combo stays the browser's.
useHistoryKeys({
  undo: () => norms.undo(),
  redo: () => norms.redo(),
  locked: () => !store.manualNorms,
})

// A norm belongs to an article: any other cut switches it off, and the
// picker greys "Target: manual" out until the cut is "SKUs" again.
watch(
  () => store.groupBy,
  (groupBy) => {
    if (groupBy !== 'sku') norms.mode = 'default'
  },
)

onMounted(() => norms.load().catch((err) => (norms.error = extractErrorMessage(err))))
</script>

<template>
  <div class="app-container py-lg">
    <PageHeader title="Heatmap" subtitle="SKUs by day: where a metric rose and where it dipped">
      <template #actions><HeatmapHelp /></template>
    </PageHeader>
    <BackfillNotice :lanes="['funnel', 'advertising', 'pnl']" />

    <HeatmapFilters
      v-model:subjects="store.subjects"
      v-model:group-ids="store.groupIds"
      v-model:nm-ids="store.nmIds"
      v-model:group-by="store.groupBy"
      :date-from="store.dateFrom"
      :date-to="store.dateTo"
      :catalog="store.catalog"
      @period="store.setPeriod"
    />

    <section
      class="rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
    >
      <HeatmapControls
        v-model:metric="store.metric"
        v-model:metric2="store.metric2"
        v-model:period="store.period"
        :group-by="store.groupBy"
        v-model:mode="store.mode"
        v-model:norm-mode="norms.mode"
        @swap="store.swapMetrics"
      />

      <DataState v-if="norms.error" kind="error" layout="line" :text="norms.error" class="mb-md" />
      <p v-if="settledNote" class="mb-sm text-tiny text-muted">{{ settledNote }}</p>
      <DataState v-if="!store.data && store.loading" kind="loading" layout="bare" />
      <DataState
        v-else-if="!store.data && store.error"
        kind="error"
        layout="bare"
        :text="store.error"
      />

      <template v-if="store.data && store.primary">
        <DataState
          v-if="store.error"
          kind="error"
          layout="line"
          :text="store.error"
          class="mb-md"
        />
        <BusyRegion :busy="store.loading">
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
        </BusyRegion>
      </template>
    </section>

    <!-- Under the card, like the monitoring matrix's edit hint. -->
    <p v-if="store.manualNorms" class="mt-sm text-tiny text-muted">
      <kbd class="ui-kbd">Ctrl</kbd>+<kbd class="ui-kbd">Z</kbd>
      — undo,
      <kbd class="ui-kbd">Ctrl</kbd>+<kbd class="ui-kbd">Shift</kbd>+<kbd class="ui-kbd">Z</kbd> —
      redo.
    </p>
  </div>
</template>
