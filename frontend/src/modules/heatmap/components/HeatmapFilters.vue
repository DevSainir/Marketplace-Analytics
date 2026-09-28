<script setup>
/**
 * The row above the grid: the period and the three filters that decide WHICH
 * articles the heatmap covers — «Категории», «Группы», «Артикулы».
 *
 * They combine by intersection, and an empty filter means «все». «Группы» is
 * the one with more to it: its menu ends in «Добавить группу», and every group
 * carries a pencil that opens it for editing — the list of groups is where a
 * seller looks for them, so that is where they are managed.
 *
 * Dumb by contract: options in, selections and intents out.
 */
import { computed, ref } from 'vue'

import PeriodSelector from '@/core/components/PeriodSelector.vue'
import { formatSku } from '@/core/utils/format'
import HeatmapFilterMenu from '@/modules/heatmap/components/HeatmapFilterMenu.vue'

const props = defineProps({
  dateFrom: { type: String, required: true },
  dateTo: { type: String, required: true },
  /** `{items: [...cards], subjects: [...]}` from the catalogue route. */
  catalog: { type: Object, required: true },
  groups: { type: Array, default: () => [] },
  subjects: { type: Array, default: () => [] },
  groupIds: { type: Array, default: () => [] },
  nmIds: { type: Array, default: () => [] },
})
const emit = defineEmits([
  'period',
  'update:subjects',
  'update:groupIds',
  'update:nmIds',
  'add-group',
  'edit-group',
])

const subjectItems = computed(() => {
  const items = props.catalog.subjects.map((subject) => ({ value: subject, label: subject }))
  // Cards WB (or a catalogue sync that has not run yet) left without a subject
  // are still articles; they get an option of their own rather than vanishing.
  if (props.catalog.items.some((card) => !card.subject_name)) {
    items.push({ value: '', label: '(не указан)' })
  }
  return items
})

const groupItems = computed(() =>
  props.groups.map((group) => ({
    value: group.id,
    label: group.name,
    sub: `Артикулов: ${group.nm_ids.length}`,
  })),
)

const skuItems = computed(() =>
  props.catalog.items.map((card) => ({
    value: card.nm_id,
    label: formatSku(card.vendor_code) ?? `SKU ${card.nm_id}`,
    sub: card.title,
    photo: card.photo_url,
  })),
)

const groupsMenu = ref(null)

/** The dialog takes over from the menu, so the menu gets out of its way. */
function addGroup() {
  groupsMenu.value?.close()
  emit('add-group')
}

function editGroup(id) {
  groupsMenu.value?.close()
  emit(
    'edit-group',
    props.groups.find((group) => group.id === id),
  )
}
</script>

<template>
  <div class="mb-md flex flex-wrap items-center gap-sm">
    <PeriodSelector :from="dateFrom" :to="dateTo" @range="emit('period', $event)" />

    <HeatmapFilterMenu
      label="Категории"
      :items="subjectItems"
      :model-value="subjects"
      placeholder="Поиск категории…"
      empty-text="Категорий нет — они появятся после синхронизации каталога"
      @update:model-value="emit('update:subjects', $event)"
    />

    <HeatmapFilterMenu
      ref="groupsMenu"
      label="Группы"
      :items="groupItems"
      :model-value="groupIds"
      badge
      empty-text="Групп пока нет"
      @update:model-value="emit('update:groupIds', $event)"
    >
      <template #action="{ item }">
        <button
          type="button"
          class="shrink-0 rounded-btn px-sm py-xs text-tiny text-muted transition hover:text-action"
          :aria-label="`Изменить группу ${item.label}`"
          @click="editGroup(item.value)"
        >
          ✎
        </button>
      </template>
      <template #footer>
        <button type="button" class="text-tiny font-semibold text-action" @click="addGroup">
          + Добавить группу
        </button>
      </template>
    </HeatmapFilterMenu>

    <HeatmapFilterMenu
      label="Артикулы"
      :items="skuItems"
      :model-value="nmIds"
      placeholder="Артикул, название или nm ID"
      @update:model-value="emit('update:nmIds', $event)"
    />
  </div>
</template>
