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
import RefreshProgress from '@/core/components/RefreshProgress.vue'

defineProps({
  /** Whether the working copy carries unsaved manual edits. */
  dirty: { type: Boolean, default: false },
  /** A save (PUT) is in flight. */
  saving: { type: Boolean, default: false },
  /** A WB re-harvest ("Refresh") is in flight. */
  refreshing: { type: Boolean, default: false },
  /**
   * Staged progress of the in-flight refresh, `{ percent, message }` or null.
   * A first run can take ~8 minutes, and a disabled button for that long reads
   * as a hung request rather than a slow one.
   */
  progress: { type: Object, default: null },
  /** A detail fetch is in flight (blocks the refresh alongside the others). */
  loading: { type: Boolean, default: false },
  /** Transient message from the last failed action, if any. */
  error: { type: String, default: null },
  /**
   * The last action completed, but WB withheld part of its data — so part of
   * the table is deliberately unchanged. Distinct from `error`: nothing failed,
   * and the user's own next move is to wait, not to retry.
   */
  warning: { type: String, default: null },
})

defineEmits(['save', 'refresh'])
</script>

<template>
  <!-- Hint on the left, actions on the right. The dirty caption sits
     UNDER the buttons so its appearance moves nothing. -->
  <div class="mt-sm flex flex-wrap items-start gap-md">
    <p class="min-w-0 text-tiny text-muted">
      Click a value to edit it — dependent cells recalculate.
      <kbd class="ui-kbd">Ctrl</kbd>+<kbd class="ui-kbd">Z</kbd>
      undoes,
      <kbd class="ui-kbd">Ctrl</kbd>+<kbd class="ui-kbd">Shift</kbd>+<kbd class="ui-kbd">Z</kbd>
      redoes.
    </p>

    <!-- The keyboard hint above is desktop advice (there is no Ctrl+Z on a
         phone), so on a phone the actions come first and take the full width
         rather than sitting as two stubs at the right edge. -->
    <div class="ml-auto flex flex-wrap items-center gap-sm phone:order-first phone:w-full">
      <span v-if="dirty" class="text-base font-bold text-status-warning"> Unsaved changes </span>
      <button
        type="button"
        :disabled="!dirty || saving || refreshing"
        class="ui-btn ui-btn--primary phone:flex-1"
        @click="$emit('save')"
      >
        {{ saving ? 'Saving…' : 'Save' }}
      </button>
      <button
        type="button"
        :disabled="loading || refreshing || saving"
        class="ui-btn phone:flex-1"
        @click="$emit('refresh')"
      >
        {{ refreshing ? 'Refreshing…' : 'Refresh' }}
      </button>
    </div>
  </div>

  <!--
    Under the buttons, like the unsaved-changes caption above: a bar that
    appeared between the hint and the actions would shift the button the user
    is waiting to press again.
  -->
  <div v-if="refreshing" class="mt-xs flex justify-end">
    <RefreshProgress :percent="progress?.percent ?? null" :message="progress?.message ?? ''" />
  </div>

  <p v-if="error" class="mt-xs text-tiny text-status-negative" role="alert">
    {{ error }}
  </p>

  <p v-else-if="warning" class="mt-xs text-tiny text-status-warning" role="status">
    {{ warning }}
  </p>
</template>
