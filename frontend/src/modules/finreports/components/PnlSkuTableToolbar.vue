<script setup>
/**
 * The per-SKU table's toolbar: the search, the Предмет / Бренд filters, a
 * «Сбросить фильтр» while any is set, and the page-size picker.
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

import SearchField from '@/core/components/SearchField.vue'

const props = defineProps({
  /** Distinct Предмет values for the dropdown. */
  subjects: { type: Array, default: () => [] },
  /** Distinct Бренд values for the dropdown. */
  brands: { type: Array, default: () => [] },
  query: { type: String, default: '' },
  subject: { type: String, default: '' },
  brand: { type: String, default: '' },
  pageSize: { type: Number, default: 50 },
  pageSizes: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:query', 'update:subject', 'update:brand', 'update:pageSize'])

const filtering = computed(() => Boolean(props.query || props.subject || props.brand))

function clear() {
  emit('update:query', '')
  emit('update:subject', '')
  emit('update:brand', '')
}
</script>

<template>
  <!-- The app's one table toolbar, the same row advertising has: above the
       table's card, search → filters → «Сбросить фильтр» → page size right. -->
  <div class="mb-sm flex flex-wrap items-center gap-sm">
    <SearchField
      :model-value="query"
      size="sm"
      class="w-72 phone:w-full"
      @update:model-value="emit('update:query', $event)"
    />
    <select
      :value="subject"
      aria-label="Предмет"
      class="ui-select ui-select--sm min-w-0 phone:w-full"
      @change="emit('update:subject', $event.target.value)"
    >
      <option value="">Все предметы</option>
      <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
    </select>
    <select
      :value="brand"
      aria-label="Бренд"
      class="ui-select ui-select--sm min-w-0 phone:w-full"
      @change="emit('update:brand', $event.target.value)"
    >
      <option value="">Все бренды</option>
      <option v-for="b in brands" :key="b" :value="b">{{ b }}</option>
    </select>
    <button v-if="filtering" type="button" class="ui-btn ui-btn--ghost ui-btn--sm" @click="clear">
      Сбросить фильтр
    </button>
    <!-- Page size belongs to the DataTable's paginator; the phone card list
         grows with its own «Показать ещё», so this control would do nothing
         there and reads as broken. -->
    <div v-if="pageSizes.length" class="ml-auto hidden items-center gap-sm sm:flex">
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
