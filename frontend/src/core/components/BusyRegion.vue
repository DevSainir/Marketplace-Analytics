<script setup>
/**
 * A block whose figures are being replaced: they stay, dimmed and inert, with
 * the busy bar across the top until the new ones land.
 *
 * The one way the app reloads data already on screen. Pages used to do it
 * three ways — dim and lock, dim but leave clickable, or blank the block behind
 * a «loading» line — and blanking was the worst of them: a flag toggled or a
 * period changed made the whole table vanish and the page jump.
 *
 * Inert, not just faded: a click on a stale row would act on figures that are
 * about to change under it.
 */
import BusyBar from '@/core/components/BusyBar.vue'

defineProps({
  busy: { type: Boolean, default: false },
})
</script>

<template>
  <div class="relative" :aria-busy="busy">
    <BusyBar v-if="busy" full class="absolute inset-x-0 -top-sm z-10" />
    <div
      class="transition-opacity duration-150"
      :class="{ 'pointer-events-none select-none opacity-50': busy }"
      :inert="busy || undefined"
    >
      <slot />
    </div>
  </div>
</template>
