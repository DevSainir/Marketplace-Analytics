<script setup>
/**
 * One filter of the heatmap — «Категории», «Группы» or «Артикулы»: a button that
 * opens a searchable checklist.
 *
 * Nothing ticked means no filter at all, which is what a seller opening the page
 * expects: every article, not none. «Выбрать все» ticks (or clears) what the
 * search currently shows, so «найти все костюмы и отметить» is two actions.
 *
 * A кабинет can hold a thousand articles, so the list draws at most
 * {@link RENDER_LIMIT} of them and says so — the search is how a seller finds
 * the rest, and a thousand checkboxes in a popover are unusable anyway.
 *
 * Dumb by contract: it renders what it is given, emits the selection, and
 * leaves room (the `action` and `footer` slots) for what only one of the three
 * filters needs — the groups' «Добавить группу» and their edit buttons.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import SkuThumb from '@/core/components/SkuThumb.vue'

const RENDER_LIMIT = 200

const props = defineProps({
  label: { type: String, required: true },
  /** @type {Array<{value: string|number, label: string, sub?: string, photo?: string}>} */
  items: { type: Array, default: () => [] },
  modelValue: { type: Array, default: () => [] },
  placeholder: { type: String, default: 'Поиск…' },
  /** Show the marketplace badge before each option, as the reference does. */
  badge: { type: Boolean, default: false },
  emptyText: { type: String, default: 'Ничего не найдено' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const query = ref('')
const selected = computed(() => new Set(props.modelValue))

const matches = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return props.items
  return props.items.filter((item) =>
    [item.label, item.sub, String(item.value)]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(needle)),
  )
})
const shown = computed(() => matches.value.slice(0, RENDER_LIMIT))
const allShownOn = computed(
  () => shown.value.length > 0 && shown.value.every((item) => selected.value.has(item.value)),
)

function toggle(value) {
  const next = new Set(props.modelValue)
  if (next.has(value)) next.delete(value)
  else next.add(value)
  emit('update:modelValue', [...next])
}

function toggleShown() {
  const next = new Set(props.modelValue)
  for (const item of matches.value) {
    if (allShownOn.value) next.delete(item.value)
    else next.add(item.value)
  }
  emit('update:modelValue', [...next])
}

function onKey(event) {
  if (event.key === 'Escape') open.value = false
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

defineExpose({ close: () => (open.value = false) })
</script>

<template>
  <div class="relative phone:w-full">
    <button
      type="button"
      class="hm-trigger"
      :class="{ 'is-on': modelValue.length }"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="open = !open"
    >
      <span class="truncate">{{ label }}</span>
      <span v-if="modelValue.length" class="hm-trigger__count">{{ modelValue.length }}</span>
      <span class="text-tiny text-muted" aria-hidden="true">{{ open ? '▴' : '▾' }}</span>
    </button>

    <div v-if="open" class="fixed inset-0 z-30" @click="open = false"></div>

    <div v-if="open" class="hm-menu ui-pop" role="listbox" aria-multiselectable="true">
      <input
        v-model="query"
        type="search"
        class="ui-input w-full"
        :placeholder="placeholder"
        :aria-label="`Поиск: ${label}`"
      />

      <button
        v-if="shown.length"
        type="button"
        class="hm-option mt-sm"
        :aria-pressed="allShownOn"
        @click="toggleShown"
      >
        <span class="hm-check" :class="{ 'is-on': allShownOn }" aria-hidden="true">✓</span>
        <span class="text-base text-primary">Выбрать все</span>
      </button>

      <p v-if="!shown.length" class="py-md text-center text-tiny text-muted">{{ emptyText }}</p>

      <ul v-else class="max-h-72 overflow-y-auto">
        <li v-for="item in shown" :key="item.value" class="flex items-center">
          <button
            type="button"
            role="option"
            class="hm-option min-w-0 flex-1"
            :aria-selected="selected.has(item.value)"
            @click="toggle(item.value)"
          >
            <span class="hm-check" :class="{ 'is-on': selected.has(item.value) }" aria-hidden="true"
              >✓</span
            >
            <SkuThumb v-if="item.photo !== undefined" :src="item.photo" :label="item.label" />
            <span v-if="badge" class="hm-wb" aria-hidden="true">wb</span>
            <span class="min-w-0 flex-1 text-left">
              <span class="block truncate text-base text-primary">{{ item.label }}</span>
              <span v-if="item.sub" class="block truncate text-tiny text-muted">{{
                item.sub
              }}</span>
            </span>
          </button>
          <slot name="action" :item="item" />
        </li>
      </ul>

      <div
        class="mt-sm flex items-center justify-between gap-sm border-t border-border-subtle pt-sm"
      >
        <slot name="footer" />
        <span class="ml-auto text-tiny text-muted">
          Показано {{ shown.length }} из {{ items.length }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hm-menu {
  top: calc(100% + 6px);
  left: 0;
  width: min(22rem, calc(100vw - 32px));
  padding: 12px;
  background: var(--ui-surface);
  box-shadow: var(--ui-sh-md);
}
</style>
