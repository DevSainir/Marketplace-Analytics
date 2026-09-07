<script setup>
/**
 * The progress of a WB refresh: a bar, a percentage, and what is happening.
 *
 * A first «Обновить» can run for ~8 minutes, because it now includes the
 * account-wide sale feed and the 22-day buyout-cohort pass. Eight minutes of a
 * disabled button and a spinner is indistinguishable from a hung request, and
 * that reading is the one users reach for — «Обновить» has a history of being
 * believed broken when it was merely slow (2026-07-30).
 *
 * So this says which of the two stages is running, in the seller's own terms:
 * «реклама, воронка, остатки и цены», then «проценты выкупа». The wording comes
 * from the backend rather than being assembled here, so the stages can change
 * without the two drifting apart.
 *
 * Presentational only. It owns no polling and no state.
 */
defineProps({
  /** 0-100. Null while the task is enqueued but has not checked in yet. */
  percent: { type: Number, default: null },
  /** Russian line describing the current stage, rendered verbatim. */
  message: { type: String, default: '' },
})
</script>

<template>
  <div class="w-full max-w-xs" role="status" aria-live="polite">
    <div
      class="h-1 w-full overflow-hidden rounded-btn bg-border-subtle"
      role="progressbar"
      :aria-valuenow="percent ?? undefined"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <!--
        An indeterminate bar (percent still null) shows a resting sliver rather
        than an empty track: a 0%-wide bar and a broken one look the same.
      -->
      <div
        class="h-full rounded-btn bg-action transition-[width] duration-500 ease-out"
        :style="{ width: `${percent ?? 4}%` }"
      />
    </div>

    <!--
      The percentage is pinned in its own column rather than trailing the
      sentence: the stage messages wrap to two lines, and a number that lands
      mid-wrap stops reading as the answer to "how far along is this".
    -->
    <div v-if="message" class="mt-xs flex items-baseline justify-end gap-sm">
      <p class="text-right text-tiny font-medium text-muted">{{ message }}</p>
      <span
        v-if="percent !== null"
        class="shrink-0 text-tiny font-semibold tabular-nums text-primary"
      >
        {{ percent }}%
      </span>
    </div>
  </div>
</template>
