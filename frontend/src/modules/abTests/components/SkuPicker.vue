<script setup>
/**
 * Article picker for a new test — a search field that stays a search field.
 *
 * A free-text article field let a test be created against `1` — an article no
 * workspace owns, which the poller finds no advertising for and a rotation
 * would try to upload a photo to. The API refuses those now; this is the half
 * that stops them being typed in the first place, and it is why the separate
 * «Артикул продавца» field is gone: both identifiers reach the same card, and
 * the seller article is read off it.
 *
 * Two things it does NOT do, both of them fixes:
 *
 * * It does not swap itself for a read-only chip once a card is picked. That
 *   version needed a «сменить» button to get back, which is one control for
 *   something the field could already do. Typing is always allowed, and typing
 *   after a pick DROPS the pick — otherwise the box could read «АРТ-2» while
 *   the form still carried the card behind «АРТ-1».
 * * It does not leave the list open. The list closes on Escape and on focus
 *   leaving the whole combobox, which is what a click anywhere else does; the
 *   previous version had neither and could only be dismissed by picking. The
 *   field reopens on CLICK as well as on focus — after an Escape the input is
 *   still focused, so `@focus` alone would never fire again and the list would
 *   be unreachable without tabbing away and back.
 *
 * The order the options arrive in is the backend's — advertised cards first,
 * then last week's orders — so the list must NOT re-sort them. The two badges
 * on a row are there to make that order legible rather than arbitrary.
 */
import { ref } from 'vue'
import { formatSku } from '@/core/utils/format'

const props = defineProps({
  /** Catalogue options, in the order the store loaded them. */
  options: { type: Array, default: () => [] },
  /** The currently picked card, or null. */
  modelValue: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'search'])

const needle = ref('')
const open = ref(false)
const root = ref(null)

/** What the field shows for a card: the seller article, or the WB one. */
const label = (option) => formatSku(option.vendor_code) || String(option.nm_id)

function pick(option) {
  emit('update:modelValue', option)
  needle.value = label(option)
  open.value = false
}

/**
 * Typing re-opens the list, re-runs the search and un-picks the current card.
 *
 * Un-picking is the point: leaving the pick in place would let the field say
 * one article while the form submitted another.
 */
function onInput(event) {
  needle.value = event.target.value
  open.value = true
  if (props.modelValue) emit('update:modelValue', null)
  emit('search', needle.value)
}

function close() {
  open.value = false
}

/** Close only when focus leaves the whole combobox — option clicks keep it. */
function onFocusOut(event) {
  if (!root.value?.contains(event.relatedTarget)) close()
}

function clear() {
  needle.value = ''
  open.value = true
  emit('update:modelValue', null)
  emit('search', '')
}
</script>

<template>
  <div ref="root" class="relative" @focusout="onFocusOut" @keydown.esc="close">
    <span class="text-tiny font-medium uppercase tracking-wide text-muted">Артикул</span>

    <div class="relative mt-xs">
      <input
        :value="needle"
        data-testid="sku-search"
        class="h-11 w-full rounded-input bg-surface px-md pr-10 text-base text-primary shadow-soft placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-action/20"
        placeholder="Артикул WB, артикул продавца или название"
        role="combobox"
        :aria-expanded="open"
        @focus="open = true"
        @click="open = true"
        @input="onInput"
      />
      <button
        v-if="needle"
        type="button"
        aria-label="Очистить"
        class="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-muted transition hover:bg-hover hover:text-primary"
        data-testid="clear-sku"
        @click="clear"
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

    <p
      v-if="modelValue"
      class="mt-xs flex items-center gap-xs text-tiny text-muted"
      data-testid="picked-sku"
    >
      <svg
        class="h-3.5 w-3.5 flex-none text-status-positive"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.4"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="m5 13 4 4L19 7" />
      </svg>
      <span class="font-medium text-primary">{{ label(modelValue) }}</span>
      <span>· {{ modelValue.nm_id }}</span>
      <span v-if="modelValue.title" class="min-w-0 truncate">· {{ modelValue.title }}</span>
    </p>

    <Transition
      enter-active-class="transition duration-100 ease-out"
      enter-from-class="-translate-y-1 opacity-0"
      leave-active-class="transition duration-75 ease-in"
      leave-to-class="-translate-y-1 opacity-0"
    >
      <div
        v-if="open && options.length"
        class="absolute inset-x-0 top-full z-20 mt-xs max-h-72 overflow-y-auto rounded-card bg-surface shadow-card"
        data-testid="sku-options"
        role="listbox"
      >
        <ul class="divide-y divide-border-subtle">
          <li v-for="option in options" :key="option.nm_id">
            <button
              type="button"
              role="option"
              :aria-selected="option.nm_id === modelValue?.nm_id"
              class="flex w-full items-center gap-sm px-md py-sm text-left transition hover:bg-hover"
              data-testid="sku-option"
              @click="pick(option)"
            >
              <span class="min-w-0 flex-1">
                <span class="block truncate text-base font-medium text-primary">
                  {{ label(option) }}
                  <span class="font-body text-muted">· {{ option.nm_id }}</span>
                </span>
                <span v-if="option.title" class="block truncate text-tiny text-muted">
                  {{ option.title }}
                </span>
              </span>
              <span
                v-if="option.has_ads"
                class="flex-none rounded-full bg-action/10 px-sm py-px text-micro font-semibold text-action"
                title="По карточке крутится реклама — режим «по показам» будет двигать ротацию"
              >
                реклама
              </span>
              <span class="flex-none text-micro tabular-nums text-muted">
                {{ option.orders_7d || 0 }} зак/нед
              </span>
            </button>
          </li>
        </ul>
      </div>
    </Transition>

    <p
      v-if="open && !options.length && needle"
      class="mt-xs text-tiny text-muted"
      data-testid="sku-empty"
    >
      В каталоге кабинета такого артикула нет.
    </p>
  </div>
</template>
