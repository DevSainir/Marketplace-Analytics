<script setup>
/**
 * Day-by-day metrics table (spreadsheet-like): a horizontal ribbon of day
 * sections, each one the workbook's «тип трафика × зона показов» block,
 * newest day on the right. Auto-scrolls to the newest day whenever a
 * new matrix arrives; the metric-name column stays frozen on the left while
 * scrolling (see `.app-datatable--matrix` skin in main.css).
 *
 * Rendered as a NATIVE `<table>` (not PrimeVue DataTable): the matrix is
 * ~4400 cells and PrimeVue's per-column component overhead made the initial
 * render ~1.6s; a plain table paints the same grid in ~300ms. The styling is
 * DOM-generic (`table`/`thead th`/`tbody td`), so it carries over unchanged;
 * only the scroll container moved from PrimeVue's `[data-pc-section=
 * 'tablecontainer']` to `.matrix-scroll`.
 *
 * This component owns the table shell — the three header rows, the metric
 * rows, the scroll container, and the associative-conversion hover. The rows
 * BELOW the metrics are each their own component, because each is a separate
 * editing surface with its own state and its own rules:
 *
 *   MatrixDayBlocksRow  «Цены» / «Остатки» day-bound cards
 *   MatrixCommentsRow   the per-day note (header + comment)
 *   MatrixActionsRow    the per-day «Действия» answers
 *
 * They render `<tbody>` sections of THIS table on purpose: sharing one table
 * (and therefore one scroll container) is what keeps every row's day columns
 * aligned with the metrics above them, with no scroll syncing anywhere.
 *
 * Editable cells (per the backend editability map) turn into an input on
 * click; committing (Enter/blur) emits `edit` with the raw numeric value —
 * the parent sends it to the backend, which recomputes dependents. Read-only
 * cells render as plain text.
 *
 * Header (3 rows, as in the workbook):
 *   «Дата» · «Тип получения трафика» (groups) · «Зоны показов» (leaf columns).
 * A group that ran a campaign that day links to it in WB's advertising cabinet;
 * hovering shows the id, selectable and copyable (`campaignLinks.js`).
 */
import { nextTick, onMounted, ref, watch } from 'vue'

import { vDragScroll } from '@/core/utils/dragScroll'
import AssocBreakdownTip from '@/modules/monitoring/components/AssocBreakdownTip.vue'
import CtrBasisTip from '@/modules/monitoring/components/CtrBasisTip.vue'
import CampaignIdTip from '@/modules/monitoring/components/CampaignIdTip.vue'
import { useCampaignLinks } from '@/modules/monitoring/campaignLinks'
import MatrixMetricsRows from '@/modules/monitoring/components/MatrixMetricsRows.vue'
import MatrixActionsRow from '@/modules/monitoring/components/MatrixActionsRow.vue'
import MatrixColgroup from '@/modules/monitoring/components/MatrixColgroup.vue'
import MatrixCommentsRow from '@/modules/monitoring/components/MatrixCommentsRow.vue'
import MatrixDayBlocksRow from '@/modules/monitoring/components/MatrixDayBlocksRow.vue'
import MetricsDayList from '@/modules/monitoring/components/MetricsDayList.vue'
import { DAY_COLSPAN, TRAFFIC_GROUPS } from '@/modules/monitoring/metricsMatrix'
import { useMatrixColumns } from '@/modules/monitoring/matrixColumns'
import { useAssocHover } from '@/modules/monitoring/useAssocHover'

const props = defineProps({
  /** @type {Array<{iso: string, label: string}>} oldest → newest */
  days: { type: Array, required: true },
  /** @type {Array<{key, label, tone, cells: object[]}>} day-major cell objects */
  rows: { type: Array, required: true },
  /** «Цены» block rows — one «Общая» cell per day (prices editable). */
  priceRows: { type: Array, default: () => [] },
  /** «Остатки» block rows — one «Общая» cell per day (read-only). */
  stockRows: { type: Array, default: () => [] },
  /** «Всего» card row — per-day total stock (stock + both «в пути» legs), read-only. */
  stockTotalRows: { type: Array, default: () => [] },
  /** Persisted day notes, keyed by ISO day: `{body, header}` per commented day. */
  comments: { type: Object, default: () => ({}) },
  /** ISO days whose note save is in flight (their input is disabled). */
  commentSavingDays: { type: Set, default: () => new Set() },
  /** Persisted «Действия» rows, keyed by ISO day (touched days only). */
  dayActions: { type: Object, default: () => ({}) },
  /** ISO days whose action save is in flight (their controls are disabled). */
  actionSavingDays: { type: Set, default: () => new Set() },
  /** Disable editing while a save/refresh is in flight. */
  editingDisabled: { type: Boolean, default: false },
  /** `{nmId, byDay}` — the campaign each traffic group ran, per ISO day. */
  campaigns: { type: Object, default: null },
})

const emit = defineEmits(['edit', 'comment', 'action'])

const { zoneHeaderColumns, rowColumns } = useMatrixColumns(() => props.days)

const scroll = ref(null)

const { advertFor, tip, showTip, hideTip, keepTip } = useCampaignLinks(
  () => props.campaigns,
  () => props.days,
)

/** Start at the right edge: «сегодня» first, older days appear scrolling left. */
function scrollToNewestDay() {
  if (scroll.value) scroll.value.scrollLeft = scroll.value.scrollWidth
}

const { assocTip, ctrTip, assocData, onMatrixOver, hideAssocTip } = useAssocHover(() => props.rows)

// The tip's own scroll dismissal lives in useAssocHover; this only has to put
// the ribbon at «сегодня» on first paint and after every window change.
onMounted(scrollToNewestDay)
watch(
  () => props.days,
  () => nextTick(scrollToNewestDay),
)
</script>

<template>
  <div>
    <!--
      Below `sm` the matrix is not a table at all — see MetricsDayList. The
      switch is at `sm` (640px) rather than at the `phone:` breakpoint because
      it is a capability threshold, not a phone tweak: the fixed layout divides
      the width between two day sections, so anything under ~640px squeezes the
      leaf columns until the numbers overlap. Both read the same rows.
    -->
    <MetricsDayList
      class="rounded-card border border-border-subtle bg-surface p-md shadow-card sm:hidden"
      :days="days"
      :rows="rows"
      :price-rows="priceRows"
      :stock-rows="stockRows"
      :stock-total-rows="stockTotalRows"
      :editing-disabled="editingDisabled"
      :comments="comments"
      :comment-saving-days="commentSavingDays"
      :day-actions="dayActions"
      :action-saving-days="actionSavingDays"
      @edit="emit('edit', $event)"
      @comment="emit('comment', $event)"
      @action="emit('action', $event)"
    />

    <!-- --matrix-days drives the fixed-layout width so EXACTLY two day
         sections fill the viewport (see .app-datatable--matrix in main.css);
         a one-day period gets the whole width rather than half of it. -->
    <div
      class="app-datatable app-datatable--matrix hidden sm:block"
      :style="`--matrix-days: ${days.length}; --matrix-per-screen: ${Math.min(2, days.length) || 1}`"
    >
      <div v-if="!rows.length" class="px-md py-xl text-center text-base text-muted">
        Нет данных за выбранный период.
      </div>

      <div
        v-else
        ref="scroll"
        v-drag-scroll
        class="matrix-scroll"
        @mouseover="onMatrixOver"
        @mouseleave="hideAssocTip"
      >
        <table>
          <MatrixColgroup :days="days" />
          <thead>
            <!-- Row 1: date, one label spanning each day's whole section. -->
            <tr>
              <th>Дата</th>
              <th v-for="day in days" :key="day.iso" :colspan="DAY_COLSPAN">
                {{ day.label }}
              </th>
            </tr>
            <!-- Row 2: «Тип получения трафика» groups («Общая»/«Органика» span row 3). -->
            <tr>
              <th>Тип получения трафика</th>
              <template v-for="day in days" :key="day.iso">
                <th
                  v-for="group in TRAFFIC_GROUPS"
                  :key="`${day.iso}:${group.label}`"
                  :colspan="group.span"
                  :rowspan="group.spansZones ? 2 : 1"
                >
                  <a
                    v-if="advertFor(day.iso, group.key)"
                    class="matrix-advert-link"
                    :href="advertFor(day.iso, group.key).href"
                    target="_blank"
                    rel="noopener noreferrer"
                    @mouseenter="showTip($event, advertFor(day.iso, group.key).id)"
                    @mouseleave="hideTip"
                    >{{ group.label }}</a
                  >
                  <template v-else>{{ group.label }}</template>
                </th>
              </template>
            </tr>
            <!-- Row 3: «Зоны показов» — only the zoned leaf columns. -->
            <tr>
              <th>Зоны показов</th>
              <th v-for="leaf in zoneHeaderColumns" :key="leaf.id" :colspan="leaf.colspan">
                {{ leaf.zone }}
              </th>
            </tr>
          </thead>

          <MatrixMetricsRows
            :rows="rows"
            :row-columns="rowColumns"
            :assoc-data="assocData"
            :editing-disabled="editingDisabled"
            @edit="emit('edit', $event)"
          />

          <!-- Day-bound «Цены»/«Остатки» blocks: ONE row, each day cell holding
               the two tinted cards side by side, in the SAME table so they
               scroll with their day. -->

          <MatrixDayBlocksRow
            :days="days"
            :price-rows="priceRows"
            :stock-rows="stockRows"
            :stock-total-rows="stockTotalRows"
            :editing-disabled="editingDisabled"
            @edit="emit('edit', $event)"
          />

          <MatrixCommentsRow
            :days="days"
            :comments="comments"
            :comment-saving-days="commentSavingDays"
            @comment="emit('comment', $event)"
          />

          <MatrixActionsRow
            :days="days"
            :day-actions="dayActions"
            :action-saving-days="actionSavingDays"
            @action="emit('action', $event)"
          />
        </table>
      </div>

      <AssocBreakdownTip :tip="assocTip" />
      <CtrBasisTip :tip="ctrTip" />
      <CampaignIdTip :tip="tip" @keep="keepTip" @leave="hideTip" />
    </div>
  </div>
</template>

<style scoped src="./styles/MetricsTable.css"></style>
