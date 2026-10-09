<script setup>
/**
 * «Обновить все SKU» — enqueue a WB re-harvest of the whole workspace catalogue.
 *
 * Dumb by contract: it reports the intent (`refresh`) and renders the in-flight
 * label plus any error/partial-outcome message the store hands back. It lives
 * beside the period picker and is visible with no SKU open, so its messages are
 * its own — never the metrics table's.
 */
import RefreshProgress from '@/core/components/RefreshProgress.vue'

defineProps({
  /** A bulk re-harvest is in flight. */
  refreshing: { type: Boolean, default: false },
  /**
   * Staged progress of the in-flight refresh, `{ percent, message }` or null.
   * A first run can take ~8 minutes, and a disabled button for that long reads
   * as a hung request rather than a slow one.
   */
  progress: { type: Object, default: null },
  /** Transient message from the last failed bulk refresh, if any. */
  error: { type: String, default: null },
  /**
   * The bulk refresh completed, but WB withheld part of its data — so part of
   * the catalogue is deliberately unchanged. Explains, does not alarm.
   */
  warning: { type: String, default: null },
})

defineEmits(['refresh'])
</script>

<template>
  <div class="flex flex-col items-end gap-xs">
    <button
      type="button"
      :disabled="refreshing"
      class="ui-btn ui-btn--sm"
      @click="$emit('refresh')"
    >
      {{ refreshing ? 'Обновляем…' : 'Обновить все SKU' }}
    </button>

    <RefreshProgress
      v-if="refreshing"
      :percent="progress?.percent ?? null"
      :message="progress?.message ?? ''"
    />

    <p v-if="error" class="max-w-xs text-right text-tiny text-status-negative" role="alert">
      {{ error }}
    </p>
    <p v-else-if="warning" class="max-w-xs text-right text-tiny text-status-warning" role="status">
      {{ warning }}
    </p>
  </div>
</template>
