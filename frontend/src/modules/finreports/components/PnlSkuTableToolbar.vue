<script setup>
/**
 * The per-SKU table's toolbar: the search, the «Предметы» / «Бренды» /
 * «Группы» filters (the app's `FilterMenu`, several choices each, as on the
 * heatmap), a «Сбросить фильтр» while any is set, and on the right how the
 * table is cut (`GroupingChips`) and then the page-size picker.
 *
 * Presentational — the query and filter values are `v-model`s the table owns, because the table is what
 * actually filters its rows against them. Split out of PnlSkuTable to keep that
 * component under the size limit.
 *
 * Shared with the balance grid, which scrolls instead of paginating: an empty
 * `pageSizes` hides the picker, so both tables get the identical search and
 * filters without the balance growing a control that would do nothing.
 */
import { computed } from 'vue'

import FilterMenu from '@/core/components/FilterMenu.vue'
import GroupingChips from '@/core/components/GroupingChips.vue'
import SearchField from '@/core/components/SearchField.vue'
import { GroupsFilter } from '@/modules/heatmap'

const props = defineProps({
  /** Distinct Предмет values to choose from. */
  subjects: { type: Array, default: () => [] },
  /** Distinct Бренд values to choose from. */
  brands: { type: Array, default: () => [] },
  query: { type: String, default: '' },
  /** The chosen ones — empty is «все». */
  subject: { type: Array, default: () => [] },
  brand: { type: Array, default: () => [] },
  groupIds: { type: Array, default: () => [] },
  /** How the table is cut — `GroupingChips`, at the right end, before the page size. */
  cut: { type: String, required: true },
  /** Whether the «Группы» cut is offered — see `useGroupCut`. */
  groupsReadable: { type: Boolean, default: true },
  pageSize: { type: Number, default: 50 },
  pageSizes: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'update:query',
  'update:subject',
  'update:brand',
  'update:groupIds',
  'update:cut',
  'update:pageSize',
])

const options = (values) => values.map((value) => ({ value, label: value }))

const filtering = computed(() =>
  Boolean(props.query || props.subject.length || props.brand.length || props.groupIds.length),
)

function clear() {
  emit('update:query', '')
  emit('update:subject', [])
  emit('update:brand', [])
  emit('update:groupIds', [])
}
</script>

<template>
  <!-- The app's one table toolbar, the same row advertising has: above the
       table's card, search → filters → «Сбросить фильтр» → the cut and the
       page size right. -->
  <div class="mb-sm flex flex-wrap items-center gap-sm">
    <SearchField
      :model-value="query"
      size="sm"
      class="w-72 phone:w-full"
      @update:model-value="emit('update:query', $event)"
    />
    <FilterMenu
      label="Предметы"
      :items="options(subjects)"
      :model-value="subject"
      placeholder="Поиск предмета"
      @update:model-value="emit('update:subject', $event)"
    />
    <FilterMenu
      label="Бренды"
      :items="options(brands)"
      :model-value="brand"
      placeholder="Поиск бренда"
      @update:model-value="emit('update:brand', $event)"
    />
    <GroupsFilter :model-value="groupIds" @update:model-value="emit('update:groupIds', $event)" />
    <button v-if="filtering" type="button" class="ui-btn ui-btn--ghost ui-btn--sm" @click="clear">
      Сбросить фильтр
    </button>
    <!-- Page size belongs to the DataTable's paginator; the phone card list
         grows with its own «Показать ещё», so this control would do nothing
         there and reads as broken. -->
    <GroupingChips
      class="ml-auto phone:ml-0"
      :model-value="cut"
      :groups="groupsReadable"
      @update:model-value="emit('update:cut', $event)"
    />
    <div v-if="pageSizes.length" class="hidden items-center gap-sm sm:flex">
      <label class="text-tiny text-muted" for="sku-page-size">Строк на странице:</label>
      <select
        id="sku-page-size"
        :value="pageSize"
        class="ui-select ui-select--sm"
        @change="emit('update:pageSize', Number($event.target.value))"
      >
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option>
      </select>
    </div>
  </div>
</template>
