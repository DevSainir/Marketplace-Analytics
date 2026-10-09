<script setup>
/**
 * The app's one switch track: a pill that slides its knob to the right when on.
 *
 * Only the picture. The control around it is the caller's — a `<button
 * role="switch">` for a page-wide mode (advertising's «Промо-бонусы»), a
 * `<label>` over a real checkbox for a row of settings (a manager's access) —
 * because what has to be focusable and what it says to a screen reader differs,
 * while how a switch looks must not. There were two tracks before, 20×36 and
 * 24×44, in two colours for «off».
 */
defineProps({
  on: { type: Boolean, required: true },
})
</script>

<template>
  <span
    class="relative inline-flex h-5 w-9 flex-none items-center rounded-full transition-colors"
    :class="on ? 'bg-action' : 'bg-border-strong/30'"
    aria-hidden="true"
  >
    <span
      class="absolute left-0.5 h-4 w-4 rounded-full bg-white shadow-soft transition-transform"
      :class="on ? 'translate-x-4' : 'translate-x-0'"
    />
  </span>
</template>
