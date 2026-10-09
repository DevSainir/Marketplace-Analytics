<script setup>
/**
 * The per-SKU table's toolbar: an expanding search, the Тип предмета / Бренд
 * filters, and the page-size picker.
 *
 * Presentational — it owns only the search's open/closed state; the query and
 * filter values are `v-model`s the table owns, because the table is what
 * actually filters its rows against them. Split out of PnlSkuTable to keep that
 * component under the size limit.
 *
 * Shared with the balance grid, which scrolls instead of paginating: an empty
 * `pageSizes` hides the picker, so both tables get the identical search and
 * filters without the balance growing a control that would do nothing.
 */
import { nextTick, ref } from 'vue'

defineProps({
  /** Distinct Тип предмета values for the dropdown. */
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

const searchOpen = ref(false)
const searchInput = ref(null)

async function openSearch() {
  searchOpen.value = true
  await nextTick()
  searchInput.value?.focus()
}

function closeSearch() {
  searchOpen.value = false
  emit('update:query', '')
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-sm border-b border-border-subtle px-md py-sm">
    <!-- Search: a clickable icon that expands into a full input -->
    <button
      v-if="!searchOpen"
      type="button"
      aria-label="Поиск"
      class="flex h-9 w-9 items-center justify-center rounded-input border border-border-subtle text-muted transition hover:border-action hover:text-action"
      @click="openSearch"
    >
      <svg
        class="h-4 w-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
    </button>
    <Transition
      enter-active-class="transition-all duration-150 ease-out"
      enter-from-class="w-9 opacity-0"
      leave-active-class="transition-all duration-100 ease-in"
      leave-to-class="w-9 opacity-0"
    >
      <div v-if="searchOpen" class="relative w-72">
        <svg
          class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          ref="searchInput"
          :value="query"
          type="text"
          placeholder="Артикул продавца или WB, предмет, бренд…"
          class="h-9 w-full rounded-input border border-border-subtle bg-surface pl-9 pr-9 text-base text-primary placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20"
          @input="emit('update:query', $event.target.value)"
          @keydown.esc="closeSearch"
        />
        <button
          type="button"
          aria-label="Закрыть поиск"
          class="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full text-muted transition hover:bg-canvas hover:text-primary"
          @click="closeSearch"
        >
          <svg
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Filters: Тип предмета / Бренд -->
    <select
      :value="subject"
      aria-label="Предмет"
      class="h-9 rounded-input border border-border-subtle bg-surface px-sm text-base text-primary"
      @change="emit('update:subject', $event.target.value)"
    >
      <option value="">Все предметы</option>
      <option v-for="s in subjects" :key="s" :value="s">{{ s }}</option>
    </select>
    <select
      :value="brand"
      aria-label="Бренд"
      class="h-9 rounded-input border border-border-subtle bg-surface px-sm text-base text-primary"
      @change="emit('update:brand', $event.target.value)"
    >
      <option value="">Все бренды</option>
      <option v-for="b in brands" :key="b" :value="b">{{ b }}</option>
    </select>

    <!-- Page size belongs to the DataTable's paginator; the phone card list
         grows with its own «Показать ещё», so this control would do nothing
         there and reads as broken. -->
    <div v-if="pageSizes.length" class="ml-auto hidden items-center gap-sm sm:flex">
      <label class="text-tiny text-muted" for="sku-page-size">Строк на странице:</label>
      <select
        id="sku-page-size"
        :value="pageSize"
        class="rounded-input border border-border-subtle bg-surface px-sm py-xs text-base text-primary"
        @change="emit('update:pageSize', Number($event.target.value))"
      >
        <option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option>
      </select>
    </div>
  </div>
</template>
