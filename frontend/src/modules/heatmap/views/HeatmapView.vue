<script setup>
/**
 * «Тепловая карта» — /labs/heatmap.
 *
 * Every article of the кабинет, day by day, painted by one metric: the view for
 * a кабинет with too many working articles to watch one at a time, where the
 * question is not «how is this card» but «which cards dipped, and when».
 *
 * The view composes; the store decides what costs a request. The previous grid
 * stays on screen, dimmed, while the next one loads — blanking it would turn
 * every filter click into a full rebuild of the page.
 */
import { computed, onMounted, ref } from 'vue'

import HeatmapControls from '@/modules/heatmap/components/HeatmapControls.vue'
import HeatmapDayList from '@/modules/heatmap/components/HeatmapDayList.vue'
import HeatmapFilters from '@/modules/heatmap/components/HeatmapFilters.vue'
import HeatmapGroupDialog from '@/modules/heatmap/components/HeatmapGroupDialog.vue'
import HeatmapHelp from '@/modules/heatmap/components/HeatmapHelp.vue'
import HeatmapPager from '@/modules/heatmap/components/HeatmapPager.vue'
import HeatmapTable from '@/modules/heatmap/components/HeatmapTable.vue'
import '@/modules/heatmap/components/styles/heatmap.css'
import { useHeatmapStore } from '@/modules/heatmap/store'

const store = useHeatmapStore()

const dialogOpen = ref(false)
const editing = ref(null)

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
</script>

<template>
  <div class="app-container py-lg">
    <header class="mb-lg flex flex-wrap items-start justify-between gap-md">
      <div>
        <h1 class="text-h2 font-bold text-primary">Тепловая карта</h1>
        <p class="mt-xs text-base text-muted">
          Все артикулы кабинета по дням: где растёт, где проседает
        </p>
      </div>
      <HeatmapHelp />
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
        @swap="store.swapMetrics"
      />

      <p v-if="store.error" class="mb-md text-base text-status-negative">{{ store.error }}</p>
      <p v-if="settledNote" class="mb-sm text-tiny text-muted">{{ settledNote }}</p>
      <p v-if="store.loading && !store.data" class="py-xl text-center text-base text-muted">
        Считаем…
      </p>

      <div v-if="store.data && store.primary" :class="{ 'hm-stale': store.loading }">
        <HeatmapTable
          class="hidden sm:block"
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
          @sort="store.toggleSort"
        />
        <HeatmapDayList
          class="sm:hidden"
          :columns="store.columns"
          :period="store.data.period"
          :rows="store.view.rows"
          :tints="store.tints"
          :totals="store.totals"
          :primary="store.primary"
          :secondary="store.secondary"
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
