<script setup>
/**
 * "Show more (N)" under a list that grows a page at a time — the app's one.
 *
 * There were three: an outlined button with the count in brackets, a ghost
 * one with no count at all, and a chip saying "Show more N". The count is
 * what tells a reader whether the rest is worth a tap, so it always shows.
 * A list that folds back up again says "Show less" once open (`expanded`).
 */
defineProps({
  /** How many records are still hidden. */
  remaining: { type: Number, required: true },
  /** The list is fully open and may be folded back. */
  expanded: { type: Boolean, default: false },
})
</script>

<template>
  <button type="button" class="ui-btn mt-sm w-full">
    {{ expanded ? 'Show less' : `Show more (${remaining})` }}
  </button>
</template>
