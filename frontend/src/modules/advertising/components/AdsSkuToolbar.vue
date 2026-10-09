<script setup>
/**
 * The per-article table's controls: search, the grain (артикулы / предметы /
 * бренды / группы) and the «Предметы» / «Бренды» / «Группы» filters — the
 * app's `FilterMenu`, several choices each, as on the heatmap.
 *
 * Presentational: every value is a `v-model` owned by `useAdsSource`, which is
 * what filters the rows. Wraps rather than shrinks, so on a phone each control
 * takes its own full-width line instead of being squeezed to a stub.
 */
import FilterMenu from '@/core/components/FilterMenu.vue'
import SearchField from '@/core/components/SearchField.vue'
import { AD_GROUPS } from '@/modules/advertising/skuModel'
import { GroupsFilter } from '@/modules/heatmap'

defineProps({
  query: { type: String, default: '' },
  /** The chosen ones — empty is «все». */
  subjects: { type: Array, default: () => [] },
  brands: { type: Array, default: () => [] },
  groupIds: { type: Array, default: () => [] },
  group: { type: String, required: true },
  /** `filterOptions` — what the menus offer. */
  subjectOptions: { type: Array, default: () => [] },
  brandOptions: { type: Array, default: () => [] },
  /** Whether any filter is set — shows «Сбросить фильтр». */
  filtering: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:query',
  'update:subjects',
  'update:brands',
  'update:groupIds',
  'update:group',
  'clear',
])

const options = (values) => values.map((value) => ({ value, label: value }))
</script>

<template>
  <div class="mb-sm flex flex-wrap items-center gap-sm">
    <SearchField
      :model-value="query"
      size="sm"
      class="w-72 phone:w-full"
      @update:model-value="emit('update:query', $event)"
    />

    <div class="flex flex-wrap items-center gap-xs" role="group" aria-label="Группировка">
      <button
        v-for="g in AD_GROUPS"
        :key="g.id"
        type="button"
        class="ui-chip"
        :class="{ 'is-on': group === g.id }"
        :aria-pressed="group === g.id"
        @click="emit('update:group', g.id)"
      >
        {{ g.name }}
      </button>
    </div>

    <FilterMenu
      label="Предметы"
      :items="options(subjectOptions)"
      :model-value="subjects"
      placeholder="Поиск предмета"
      @update:model-value="emit('update:subjects', $event)"
    />
    <FilterMenu
      label="Бренды"
      :items="options(brandOptions)"
      :model-value="brands"
      placeholder="Поиск бренда"
      @update:model-value="emit('update:brands', $event)"
    />
    <GroupsFilter :model-value="groupIds" @update:model-value="emit('update:groupIds', $event)" />

    <button
      v-if="filtering"
      type="button"
      class="ui-btn ui-btn--ghost ui-btn--sm"
      @click="emit('clear')"
    >
      Сбросить фильтр
    </button>
  </div>
</template>
