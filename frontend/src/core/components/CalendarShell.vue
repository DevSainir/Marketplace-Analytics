<script setup>
/**
 * The frame every date picker in the app is drawn in: the label, the trigger,
 * the popover and its month arrows.
 *
 * `PeriodSelector` (a range) and `DayPicker` (one day) used to draw these each
 * on their own, and drifted — a smaller trigger with smaller type on one, a
 * popover that knew how to stay on screen on the other. What a picker selects
 * is its own business; how it opens, closes and sits on the page is this
 * file's, so the two cannot drift again.
 *
 * The popover is kept inside the window: it opens from the trigger's left edge
 * and, if that runs past the right edge (a picker at the end of a row, or a
 * phone), it is moved left until it fits.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

defineProps({
  /** Caption before the trigger ("Period", "Day"); empty = none. */
  label: { type: String, default: '' },
  /** Accessible name of the popover. */
  ariaLabel: { type: String, required: true },
  /** Month captions over the grids, one per month shown. */
  titles: { type: Array, required: true },
  canGoPrev: { type: Boolean, default: true },
  canGoNext: { type: Boolean, default: true },
})
/**
 * `opening` fires before the popover appears, so the picker can point its view
 * at the selected dates first; `shift` carries ±1 from the month arrows.
 */
const emit = defineEmits(['opening', 'shift'])
const open = defineModel('open', { type: Boolean, default: false })

/** Gap kept between the popover and the window's edge, px. */
const EDGE = 8

const root = ref(null)
const popover = ref(null)
/** Horizontal offset from the trigger's left edge that keeps the popover on screen. */
const offset = ref(0)

async function fit() {
  offset.value = 0
  await nextTick()
  const box = popover.value?.getBoundingClientRect()
  if (!box) return
  const width = document.documentElement.clientWidth
  let shift = Math.min(0, width - EDGE - box.right)
  if (box.left + shift < EDGE) shift = EDGE - box.left
  offset.value = shift
}

function toggle() {
  if (open.value) {
    open.value = false
    return
  }
  emit('opening')
  open.value = true
  fit()
}

function onDocPointer(event) {
  if (open.value && root.value && !root.value.contains(event.target)) open.value = false
}
function onKey(event) {
  if (event.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('mousedown', onDocPointer)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocPointer)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="relative flex items-center gap-sm">
    <span v-if="label" class="text-tiny font-medium uppercase tracking-wider text-muted">
      {{ label }}
    </span>

    <button
      type="button"
      class="flex h-9 items-center gap-sm rounded-input border bg-surface px-sm text-base tabular-nums text-primary shadow-soft transition-colors hover:border-action/60 phone:min-h-11"
      :class="open ? 'border-action ring-2 ring-action/20' : 'border-border-subtle'"
      aria-haspopup="dialog"
      :aria-expanded="open"
      @click="toggle"
    >
      <svg
        class="h-4 w-4 shrink-0 text-muted"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        aria-hidden="true"
      >
        <rect x="1.75" y="2.75" width="12.5" height="11.5" rx="2" />
        <path d="M1.75 6.25h12.5M5 1.25v3M11 1.25v3" />
      </svg>
      <slot name="trigger" />
    </button>

    <transition name="cal">
      <div
        v-if="open"
        ref="popover"
        class="absolute left-0 top-[calc(100%+6px)] z-40 rounded-card border border-border-subtle bg-surface p-md shadow-card"
        :style="{ left: `${offset}px` }"
        role="dialog"
        :aria-label="ariaLabel"
      >
        <div class="mb-sm flex items-center">
          <button
            type="button"
            class="nav-btn"
            :disabled="!canGoPrev"
            aria-label="Previous month"
            @click="emit('shift', -1)"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M10 3.5 5.5 8l4.5 4.5" />
            </svg>
          </button>
          <div class="flex flex-1 justify-around px-sm text-base font-semibold text-primary">
            <span v-for="title in titles" :key="title">{{ title }}</span>
          </div>
          <button
            type="button"
            class="nav-btn"
            :disabled="!canGoNext"
            aria-label="Next month"
            @click="emit('shift', 1)"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75">
              <path d="M6 3.5 10.5 8 6 12.5" />
            </svg>
          </button>
        </div>

        <slot />
        <slot name="footer" />
      </div>
    </transition>
  </div>
</template>

<style scoped src="./styles/CalendarShell.css"></style>
