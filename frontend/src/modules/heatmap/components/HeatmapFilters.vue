<script setup>
/**
 * The row above the grid: the period and the three filters that decide WHICH
 * articles the heatmap covers — "Categories", "Groups", "SKUs" — and, at its
 * right end, what a row of the grid stands for (`GroupingChips`).
 *
 * They combine by intersection, and an empty filter means "all". "Groups" is
 * the app's shared `GroupsFilter`, where groups are also made and edited.
 *
 * Dumb by contract: options in, selections and intents out.
 */
import { computed } from 'vue'

import FilterMenu from '@/core/components/FilterMenu.vue'
import GroupingChips from '@/core/components/GroupingChips.vue'
import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { isoDaysAgo } from '@/core/utils/dates'
import { formatSku } from '@/core/utils/format'
import GroupsFilter from '@/modules/heatmap/components/GroupsFilter.vue'
import { UNNAMED } from '@/modules/heatmap/groupsStore'
import { MAX_DAYS } from '@/modules/heatmap/store'

const props = defineProps({
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
  /** `{items: [...cards], subjects: [...]}` from the catalogue route. */
  catalog: { type: Object, required: true },
  subjects: { type: Array, default: () => [] },
  groupIds: { type: Array, default: () => [] },
  nmIds: { type: Array, default: () => [] },
  /** What a row stands for — the chips at the right end of this row. */
  groupBy: { type: String, required: true },
})
const emit = defineEmits([
  'period',
  'update:subjects',
  'update:groupIds',
  'update:nmIds',
  'update:groupBy',
])

// The presets end yesterday, like the default window: today's funnel is still
// filling, and a half-day painted red beside whole ones reads as a collapse.
const yesterday = isoDaysAgo(1)

const subjectItems = computed(() => {
  const items = props.catalog.subjects.map((subject) => ({ value: subject, label: subject }))
  // Cards WB (or a catalogue sync that has not run yet) left without a subject
  // are still articles; they get an option of their own rather than vanishing.
  if (props.catalog.items.some((card) => !card.subject_name)) {
    items.push({ value: '', label: UNNAMED })
  }
  return items
})

const skuItems = computed(() =>
  props.catalog.items.map((card) => ({
    value: card.nm_id,
    label: formatSku(card.vendor_code) ?? `WB ID ${card.nm_id}`,
    sub: `Orders: ${card.orders ?? 0}${card.title ? ` · ${card.title}` : ''}`,
    photo: card.photo_url,
  })),
)
</script>

<template>
  <div class="mb-md flex flex-wrap items-center gap-sm">
    <PeriodSelector
      :from="dateFrom"
      :to="dateTo"
      :preset-end="yesterday"
      :max-days="MAX_DAYS"
      @range="emit('period', $event)"
    />

    <FilterMenu
      label="Categories"
      :items="subjectItems"
      :model-value="subjects"
      placeholder="Search categories…"
      empty-text="No categories until the catalog syncs"
      @update:model-value="emit('update:subjects', $event)"
    />

    <GroupsFilter
      :model-value="groupIds"
      :cards="catalog.items"
      @update:model-value="emit('update:groupIds', $event)"
    />

    <FilterMenu
      label="SKUs"
      :items="skuItems"
      :model-value="nmIds"
      placeholder="Vendor code, WB ID or title"
      @update:model-value="emit('update:nmIds', $event)"
    />

    <GroupingChips
      class="ml-auto phone:ml-0"
      :model-value="groupBy"
      @update:model-value="emit('update:groupBy', $event)"
    />
  </div>
</template>
