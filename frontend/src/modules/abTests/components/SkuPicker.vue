<script setup>
/**
 * Article picker for a new test.
 *
 * A free-text article field let a test be created against `1` — an article no
 * workspace owns, which the poller finds no advertising for and a rotation
 * would try to upload a photo to. The API refuses those now; this is the half
 * that stops them being typed in the first place, and it is why the separate
 * «Артикул продавца» field is gone: both identifiers reach the same card, and
 * the seller article is read off it.
 */
import { ref, watch } from 'vue'

defineProps({
  /** Catalogue options, as the store loaded them. */
  options: { type: Array, default: () => [] },
  /** The currently picked card, or null. */
  modelValue: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'search'])

const needle = ref('')
const open = ref(false)

watch(needle, (value) => emit('search', value))

function pick(option) {
  emit('update:modelValue', option)
  needle.value = ''
  open.value = false
}

function clear() {
  emit('update:modelValue', null)
  open.value = true
}
</script>

<template>
  <div class="relative">
    <span class="text-tiny font-medium uppercase tracking-wide text-muted">Артикул</span>

    <div
      v-if="modelValue"
      class="mt-xs flex items-center justify-between gap-sm rounded-control border border-border-subtle px-sm py-xs"
      data-testid="picked-sku"
    >
      <span class="text-base text-primary">
        {{ modelValue.vendor_code || modelValue.nm_id }}
        <span class="text-muted"> · {{ modelValue.nm_id }}</span>
      </span>
      <button
        type="button"
        class="text-tiny text-action hover:underline"
        data-testid="clear-sku"
        @click="clear"
      >
        сменить
      </button>
    </div>

    <input
      v-else
      v-model="needle"
      data-testid="sku-search"
      class="mt-xs w-full rounded-control border border-border-subtle px-sm py-xs text-base"
      placeholder="Артикул WB, артикул продавца или название"
      @focus="open = true"
    />

    <ul
      v-if="!modelValue && open && options.length"
      class="absolute z-10 mt-xs max-h-64 w-full overflow-y-auto rounded-card border border-border-subtle bg-surface shadow-card"
      data-testid="sku-options"
    >
      <li v-for="option in options" :key="option.nm_id">
        <button
          type="button"
          class="block w-full px-sm py-xs text-left text-base hover:bg-zebra"
          data-testid="sku-option"
          @click="pick(option)"
        >
          <span class="font-medium text-primary">{{ option.vendor_code || option.nm_id }}</span>
          <span class="text-muted"> · {{ option.nm_id }}</span>
          <span v-if="option.title" class="block text-tiny text-muted">{{ option.title }}</span>
        </button>
      </li>
    </ul>

    <p
      v-else-if="!modelValue && open && needle"
      class="mt-xs text-tiny text-muted"
      data-testid="sku-empty"
    >
      В каталоге рабочего пространства такого артикула нет.
    </p>
  </div>
</template>
