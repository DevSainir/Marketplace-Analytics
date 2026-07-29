<script setup>
/**
 * The bar under the metrics table: how to edit it, and what to do with edits.
 *
 * Layout is deliberate — the hint sits left, the actions right, and the
 * unsaved-changes caption goes UNDER the buttons so its appearance shifts
 * nothing on screen. A warning that pushed the button you were about to press
 * would be worse than no warning.
 *
 * Dumb by contract: every button reports intent and the view owns the store.
 */
defineProps({
  /** Whether the working copy carries unsaved manual edits. */
  dirty: { type: Boolean, default: false },
  /** A save (PUT) is in flight. */
  saving: { type: Boolean, default: false },
  /** A WB re-harvest («Обновить») is in flight. */
  refreshing: { type: Boolean, default: false },
  /** A detail fetch is in flight (blocks the refresh alongside the others). */
  loading: { type: Boolean, default: false },
  /** Transient message from the last failed action, if any. */
  error: { type: String, default: null },
})

defineEmits(['save', 'refresh'])
</script>

<template>
  <!-- Hint on the left, actions on the right. The dirty caption sits
     UNDER the buttons so its appearance moves nothing. -->
  <div class="mt-sm flex flex-wrap items-start gap-md">
    <p class="min-w-0 text-tiny text-muted">
      Кликните по значению, чтобы изменить его — зависимые ячейки пересчитаются.
      <kbd class="rounded border border-border-subtle px-1">Ctrl</kbd>+<kbd
        class="rounded border border-border-subtle px-1"
        >Z</kbd
      >
      — отменить,
      <kbd class="rounded border border-border-subtle px-1">Ctrl</kbd>+<kbd
        class="rounded border border-border-subtle px-1"
        >Shift</kbd
      >+<kbd class="rounded border border-border-subtle px-1">Z</kbd> — повторить.
    </p>

    <div class="ml-auto flex items-center gap-sm">
      <span v-if="dirty" class="text-base font-bold text-status-warning">
        Есть несохранённые изменения
      </span>
      <button
        type="button"
        :disabled="!dirty || saving || refreshing"
        class="inline-flex h-9 items-center justify-center rounded-btn bg-surface px-lg text-base font-medium text-primary shadow-soft transition hover:bg-hover disabled:cursor-not-allowed disabled:text-muted disabled:opacity-60"
        @click="$emit('save')"
      >
        {{ saving ? 'Сохраняем…' : 'Сохранить' }}
      </button>
      <button
        type="button"
        :disabled="loading || refreshing || saving"
        class="inline-flex h-9 items-center justify-center rounded-btn bg-action px-lg text-base font-semibold text-white shadow-soft transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60"
        @click="$emit('refresh')"
      >
        {{ refreshing ? 'Обновляем из Wildberries…' : 'Обновить' }}
      </button>
    </div>
  </div>

  <p v-if="error" class="mt-xs text-tiny text-status-negative" role="alert">
    {{ error }}
  </p>
</template>
