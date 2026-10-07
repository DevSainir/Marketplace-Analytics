<script setup>
/**
 * The app's one «work in progress» mark: a bar with a glide running along it.
 *
 * Every page used to say «loading» its own way — a dimmed block on one, a line
 * of text on another, this bar on a third. Now there is this bar: under the
 * «Загружаем…» line of a first load (`DataState`), and alone across the top of
 * a block whose figures are being replaced (`BusyRegion`).
 *
 * Indeterminate on purpose: the server reports no progress for a page load,
 * and a percentage invented on the client is a claim the page cannot support.
 * An update FROM WB does report one, and has its own bar (`RefreshProgress`).
 */
defineProps({
  /** Line beside the bar; empty = none shown (the status is still announced). */
  label: { type: String, default: '' },
  /** Run the track the full width of its container rather than a short stub. */
  full: { type: Boolean, default: false },
})
</script>

<template>
  <div class="busy" role="status" aria-live="polite">
    <div class="busy__track" :class="{ 'busy__track--full': full }">
      <span class="busy__glide"></span>
    </div>
    <p v-if="label" class="busy__label">{{ label }}</p>
    <span v-else class="sr-only">Загружаем…</span>
  </div>
</template>

<style scoped src="./styles/BusyBar.css"></style>
