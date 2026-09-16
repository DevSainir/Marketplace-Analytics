<script setup>
/**
 * Who this test is: its name, the card it runs on, and how it rotates.
 *
 * Split out of the page for size, and it earns the split: everything here is
 * identity and lifecycle, and nothing below the header reads any of it. The two
 * buttons are the two things you can do to a test as a whole — edit how it
 * rotates, or delete it — so they live with the name rather than with the
 * figures.
 *
 * Deleting arms itself here rather than in the page: the confirmation is a
 * property of the button, and the page only wants to know that the test is
 * gone so it can navigate away from a screen with nothing behind it.
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { STATUS_LABELS } from '@/modules/abTests'

const props = defineProps({
  /** The open test, or null while it loads. */
  test: { type: Object, default: null },
  /** True while a write is in flight. */
  saving: { type: Boolean, default: false },
})
const emit = defineEmits(['delete', 'edit-trigger'])

/** How this test rotates, in words — only the setting its mode actually uses. */
const triggerLabel = computed(() => {
  if (!props.test) return ''
  return props.test.trigger_mode === 'time'
    ? `Смена фото каждые ${count(props.test.slot_minutes)} мин`
    : `Смена фото каждые ${count(props.test.impression_budget)} показов`
})

/** Whether the trigger may still be edited — a finished test's is history. */
const canEditTrigger = computed(
  () => !!props.test && !['completed', 'cancelled'].includes(props.test.status),
)

const armed = ref(false)

/** Two-click confirm: the first press asks, the second one does it. */
function remove() {
  if (!armed.value) {
    armed.value = true
    return
  }
  armed.value = false
  emit('delete')
}

function count(value) {
  return Number(value ?? 0).toLocaleString('ru-RU')
}
</script>

<template>
  <header class="mb-lg">
    <RouterLink
      :to="{ name: 'ab-tests' }"
      class="text-tiny font-medium text-action hover:underline"
    >
      ← Ко всем A/Б-тестам
    </RouterLink>

    <div v-if="test" class="mt-sm flex flex-wrap items-center gap-x-md gap-y-xs">
      <h1 class="text-h2 font-bold text-primary">{{ test.name }}</h1>
      <span class="text-tiny font-semibold text-action">WB {{ test.nm_id }}</span>
      <span v-if="test.vendor_code" class="text-tiny text-muted">{{ test.vendor_code }}</span>
      <button
        type="button"
        class="ml-auto rounded-btn px-sm py-xs text-micro font-semibold transition"
        :class="
          armed
            ? 'bg-status-negative/10 text-status-negative'
            : 'text-muted hover:bg-hover hover:text-status-negative'
        "
        :disabled="saving"
        data-testid="delete-test"
        @click="remove"
      >
        {{ armed ? 'Точно удалить тест?' : 'Удалить тест' }}
      </button>
    </div>

    <p v-if="test" class="mt-xs flex flex-wrap items-center gap-x-sm text-tiny text-muted">
      <span>{{ STATUS_LABELS[test.status] || test.status }}</span>
      <span>·</span>
      <span>{{ triggerLabel }}</span>
      <button
        v-if="canEditTrigger"
        type="button"
        class="rounded-btn px-xs py-px text-micro font-semibold text-action transition hover:bg-action/10"
        data-testid="edit-trigger"
        @click="emit('edit-trigger')"
      >
        изменить
      </button>
    </p>

    <slot />
  </header>
</template>
