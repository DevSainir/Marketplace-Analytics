<script setup>
/**
 * The per-article table's controls: search, the grain (артикулы / предметы /
 * бренды) and the subject and brand filters.
 *
 * Presentational: every value is a `v-model` owned by `useAdsSource`, which is
 * what filters the rows. Wraps rather than shrinks, so on a phone each control
 * takes its own full-width line instead of being squeezed to a stub.
 */
import SearchField from '@/core/components/SearchField.vue'
import { AD_GROUPS } from '@/modules/advertising/skuModel'

defineProps({
  query: { type: String, default: '' },
  subject: { type: String, default: '' },
  brand: { type: String, default: '' },
  group: { type: String, required: true },
  /** `filterOptions` — the selects' choices. */
  subjects: { type: Array, default: () => [] },
  brands: { type: Array, default: () => [] },
  /** Whether any filter is set — shows «Сбросить фильтр». */
  filtering: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:query',
  'update:subject',
  'update:brand',
  'update:group',
  'clear',
])

const field = 'ui-select ui-select--sm min-w-0 phone:w-full'
</script>

<template>
  <div class="mb-sm flex flex-wrap items-center gap-sm">
    <SearchField
      :model-value="query"
      size="sm"
      class="w-72 phone:w-full"
      @update:model-value="emit('update:query', $event)"
    />

    <div class="flex items-center gap-xs" role="group" aria-label="Группировка">
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

    <select
      :value="subject"
      aria-label="Предмет"
      :class="field"
      @change="emit('update:subject', $event.target.value)"
    >
      <option value="">Все предметы</option>
      <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
    </select>

    <select
      :value="brand"
      aria-label="Бренд"
      :class="field"
      @change="emit('update:brand', $event.target.value)"
    >
      <option value="">Все бренды</option>
      <option v-for="b in brands" :key="b" :value="b">{{ b }}</option>
    </select>

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
