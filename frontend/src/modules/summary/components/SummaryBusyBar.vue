<script setup>
/**
 * What the page shows while a window is being fetched.
 *
 * Presets used to change nothing visible: the dates moved, the chips restyled,
 * and the figures below stayed exactly as they were until the response landed
 * seconds later — which reads as a frozen screen rather than as work in
 * progress. A window is genuinely slow to compute the first time it is asked
 * for (the кабинет's whole history is a rebuild of the settlement rollup), so
 * the state has to be visible rather than instantaneous.
 *
 * Indeterminate on purpose: the server reports no progress for this, and a
 * percentage invented on the client is a claim the page cannot support.
 */
defineProps({
  /** Russian line under the bar, rendered verbatim. */
  label: { type: String, default: 'Считаю период…' },
})
</script>

<template>
  <div class="sum-busy" role="status" aria-live="polite">
    <div class="sum-busy__track"><span class="sum-busy__glide"></span></div>
    <p class="sum-busy__label">{{ label }}</p>
  </div>
</template>

<style scoped>
.sum-busy {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sum-busy__track {
  position: relative;
  width: 132px;
  height: 3px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--ui-rule);
}

.sum-busy__glide {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 40%;
  border-radius: 2px;
  background: var(--ui-action);
  animation: sum-glide 1.1s ease-in-out infinite;
}

.sum-busy__label {
  font-size: 0.75rem;
  color: var(--ui-muted);
}

@keyframes sum-glide {
  0% {
    left: -40%;
  }

  100% {
    left: 100%;
  }
}

/* A moving bar is exactly the thing a reduced-motion setting is about; the
   state still has to be visible, so it rests as a pulse instead. */
@media (prefers-reduced-motion: reduce) {
  .sum-busy__glide {
    left: 0;
    width: 100%;
    animation: sum-pulse 1.6s ease-in-out infinite;
  }

  @keyframes sum-pulse {
    0%,
    100% {
      opacity: 0.35;
    }

    50% {
      opacity: 1;
    }
  }
}
</style>
