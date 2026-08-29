<script setup>
/**
 * «Артикулы» — which SKUs the account-wide charts cover.
 *
 * Multi-select rather than a single picker, because the page's question is
 * «how is the account doing» and the useful narrowings are a brand, a category
 * or a handful of cards — not one. The empty selection therefore means ALL
 * SKUs rather than none: a chart page that opened showing nothing until you
 * chose something would be a worse default than the whole account.
 *
 * The trigger states what is included in words, so the page never lies about
 * its own scope while the menu is shut.
 *
 * Dumb by contract: it renders the list it is given and emits the selection.
 */
import { computed, ref } from 'vue'

import { formatSku } from '@/core/utils/format'

const props = defineProps({
  /** @type {Array<{nm_id: number, vendor_code?: string, title?: string}>} */
  items: { type: Array, default: () => [] },
  /** Selected nm_ids; EMPTY means every SKU (see above). */
  modelValue: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const query = ref('')

const selected = computed(() => new Set(props.modelValue))

/** Match on article, nm ID and title — whichever the user happens to remember. */
const visible = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return props.items
  return props.items.filter((item) =>
    [item.vendor_code, String(item.nm_id), item.title]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(needle)),
  )
})

const label = computed(() => {
  if (!props.modelValue.length) return `Все артикулы (${props.items.length})`
  if (props.modelValue.length === 1) {
    const only = props.items.find((item) => item.nm_id === props.modelValue[0])
    return formatSku(only?.vendor_code) ?? `SKU ${props.modelValue[0]}`
  }
  return `Выбрано артикулов: ${props.modelValue.length}`
})

function toggle(nmId) {
  const next = new Set(props.modelValue)
  if (next.has(nmId)) next.delete(nmId)
  else next.add(nmId)
  emit('update:modelValue', [...next])
}

/** Clearing the selection is what «все» means here — not selecting every id. */
function selectAll() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="relative">
    <button
      type="button"
      class="flex h-9 w-full items-center justify-between gap-sm rounded-input border border-border-subtle bg-surface px-md text-base text-primary transition hover:bg-hover phone:h-11"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="open = !open"
    >
      <span class="truncate">{{ label }}</span>
      <span class="shrink-0 text-tiny text-muted" aria-hidden="true">▾</span>
    </button>

    <!-- Click-away closes it; the backdrop is a sibling so it cannot swallow
         clicks meant for the list itself. -->
    <div v-if="open" class="fixed inset-0 z-10" @click="open = false"></div>

    <div
      v-if="open"
      class="absolute z-20 mt-xs w-full rounded-card border border-border-subtle bg-surface p-sm shadow-card"
      role="listbox"
      aria-multiselectable="true"
    >
      <input
        v-model="query"
        type="text"
        class="h-9 w-full rounded-input border border-border-subtle bg-canvas px-sm text-base text-primary placeholder:text-muted"
        placeholder="Артикул, nm ID или название"
        aria-label="Поиск артикула"
      />

      <div class="mt-sm flex items-center justify-between text-tiny">
        <span class="text-muted">
          {{ modelValue.length ? `Выбрано: ${modelValue.length}` : 'Считаем все артикулы' }}
        </span>
        <button
          v-if="modelValue.length"
          type="button"
          class="rounded-btn px-sm py-1 font-medium text-action transition hover:bg-hover"
          @click="selectAll"
        >
          Выбрать все
        </button>
      </div>

      <p v-if="loading" class="mt-sm py-md text-center text-tiny text-muted">Загружаем список…</p>
      <p v-else-if="!visible.length" class="mt-sm py-md text-center text-tiny text-muted">
        Ничего не найдено
      </p>

      <ul v-else class="mt-xs max-h-64 overflow-y-auto">
        <li v-for="item in visible" :key="item.nm_id">
          <button
            type="button"
            role="option"
            :aria-selected="selected.has(item.nm_id)"
            class="flex w-full items-center gap-sm rounded-btn px-sm py-xs text-left transition hover:bg-hover"
            @click="toggle(item.nm_id)"
          >
            <span
              class="flex h-4 w-4 shrink-0 items-center justify-center rounded border text-white"
              :class="
                selected.has(item.nm_id)
                  ? 'border-action bg-action'
                  : 'border-border-subtle bg-canvas'
              "
              aria-hidden="true"
            >
              <span v-if="selected.has(item.nm_id)" class="text-micro leading-none">✓</span>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-base text-primary">
                {{ formatSku(item.vendor_code) ?? `SKU ${item.nm_id}` }}
              </span>
              <span v-if="item.title" class="block truncate text-tiny text-muted">
                {{ item.title }}
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>
