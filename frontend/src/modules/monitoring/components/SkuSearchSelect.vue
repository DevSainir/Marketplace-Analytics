<script setup>
/**
 * SKU search combobox (dumb): apply button on the left, a long search input,
 * and a dropdown the full width of the bar listing every SKU passed in.
 *
 * It never fetches: the parent provides `items` (the summary listing) and the
 * component only filters them locally as the user types. Picking an item emits
 * `select`; submitting the form emits `apply` with the raw query.
 */
import { computed, ref } from 'vue'

import BusyBar from '@/core/components/BusyBar.vue'
import SkuThumb from '@/core/components/SkuThumb.vue'
import { formatSku } from '@/core/utils/format'

const props = defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  /** nm ID of the currently analyzed SKU (highlighted in the list). */
  selectedId: { type: Number, default: null },
})

const emit = defineEmits(['select', 'apply'])

const query = ref('')
const open = ref(false)
const root = ref(null)
const input = ref(null)

/** The ✕ button: clear the query and put the caret back in the input. */
function clearQuery() {
  query.value = ''
  input.value?.focus()
  open.value = true
}

// Case-insensitive match over everything a manager may paste: seller article,
// card title or the raw nm ID.
const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return props.items
  return props.items.filter((item) =>
    [item.vendor_code, item.title, String(item.nm_id)].some((field) =>
      field?.toLowerCase().includes(needle),
    ),
  )
})

function close() {
  open.value = false
}

/** Close only when focus leaves the whole combobox (item clicks keep it). */
function onFocusOut(event) {
  if (!root.value?.contains(event.relatedTarget)) close()
}

function onSelect(item) {
  query.value = formatSku(item.vendor_code) || String(item.nm_id)
  close()
  emit('select', item)
}

function onApply() {
  close()
  emit('apply', query.value.trim())
}
</script>

<template>
  <div ref="root" class="relative" @focusout="onFocusOut" @keydown.esc="close">
    <!-- On a phone «Применить» beside the field leaves the input too narrow to
         show an артикул, so the pair stacks and each takes the full width. -->
    <form class="flex items-stretch gap-sm phone:flex-col" @submit.prevent="onApply">
      <div class="relative flex-1">
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
          ref="input"
          v-model="query"
          type="text"
          role="combobox"
          :aria-expanded="open"
          placeholder="Выберите SKU из списка или начните вводить артикул…"
          class="h-12 w-full rounded-input border border-border-subtle bg-surface pl-9 pr-10 text-base text-primary shadow-soft placeholder:text-muted focus:border-action focus:outline-none focus:ring-2 focus:ring-action/20"
          @focus="open = true"
          @input="open = true"
        />
        <button
          v-if="query"
          type="button"
          aria-label="Очистить поиск"
          class="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-muted transition hover:bg-canvas hover:text-primary"
          @click="clearQuery"
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

      <button
        type="submit"
        class="inline-flex h-12 flex-none items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action phone:h-11"
      >
        Применить
      </button>
    </form>

    <!-- Dropdown: full width of the bar, all SKUs, filtered live -->
    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="-translate-y-1 opacity-0"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="-translate-y-1 opacity-0"
    >
      <div
        v-if="open"
        class="absolute inset-x-0 top-full z-20 mt-sm max-h-96 overflow-y-auto rounded-card bg-surface shadow-card"
        role="listbox"
      >
        <BusyBar v-if="loading" label="Загружаем…" class="px-md py-md" />
        <p v-else-if="!filtered.length" class="px-md py-md text-base text-muted">
          Ничего не совпало — проверьте артикул или очистите поиск.
        </p>
        <ul v-else class="divide-y divide-border-subtle">
          <li v-for="item in filtered" :key="item.nm_id">
            <button
              type="button"
              role="option"
              :aria-selected="item.nm_id === selectedId"
              class="flex w-full items-center gap-sm px-md py-sm text-left transition hover:bg-action/10"
              :class="item.nm_id === selectedId ? 'bg-action/10' : ''"
              @click="onSelect(item)"
            >
              <SkuThumb
                :src="item.photo_url"
                :label="formatSku(item.vendor_code) || String(item.nm_id)"
                size="md"
              />
              <span class="text-base font-semibold text-primary">
                {{ formatSku(item.vendor_code) || item.nm_id }}
              </span>
              <span class="min-w-0 flex-1 truncate text-base text-muted">{{ item.title }}</span>
              <span
                v-if="item.is_out_of_stock"
                class="flex-none rounded-full bg-status-negative/10 px-sm text-tiny font-medium text-status-negative"
              >
                нет на складе
              </span>
              <span class="flex-none text-tiny tabular-nums text-muted">WB {{ item.nm_id }}</span>
            </button>
          </li>
        </ul>
      </div>
    </Transition>
  </div>
</template>
