<script setup>
/**
 * Floating section nav — a glass pill docked to the bottom of the viewport.
 *
 * The one component on this page that is NOT a copy of a monitoring one: the
 * real page has no equivalent. It earns its place twice over — it is the best
 * glass surface available (fixed over whatever is scrolling, always a live
 * backdrop, no positioned children), and the page is several tall blocks deep, so
 * without it the only way back from the bottom of the page is the wheel.
 *
 * Takes the MINI glass tier: it carries a handful of short words, so it can afford to
 * be transparent enough that you can see the effect working.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { currentSectionId } from '@/core/utils/sectionSpy'

const props = defineProps({
  /** @type {Array<{id: string, label: string}>} in page order */
  sections: { type: Array, required: true },
})

const active = ref(props.sections[0]?.id ?? null)

/** Until this moment, ignore the scroll: a click has already decided. */
let clickHoldsUntil = 0

/** How long a click owns the highlight — long enough for one smooth scroll. */
const CLICK_HOLD_MS = 900

/** Pending rAF handle, so a burst of scroll events costs one read. */
let frame = 0

/**
 * Set the highlight from the scroll position: the last section that has started.
 *
 * Read directly rather than through an IntersectionObserver, which is what this
 * used to do. An observer answers «is this element inside a band», which is a
 * different question from «which section am I in», and the two only coincide
 * while every section is taller than the band — the last one here is not, so it
 * could never light. An observer is also allowed to stay silent: it delivers
 * nothing at all while the document is hidden, so the highlight could arrive
 * stale and simply stay that way. A position is a fact that can be read at any
 * moment, from any scroll event, and cannot be withheld.
 *
 * The decision itself lives in `core/utils/sectionSpy` so it can be tested
 * against positions; this only reads them off the DOM.
 */
function syncToScroll() {
  if (Date.now() < clickHoldsUntil) return

  active.value = currentSectionId({
    sections: props.sections
      .map((section) => {
        const el = document.getElementById(section.id)
        return el ? { id: section.id, top: el.getBoundingClientRect().top } : null
      })
      .filter(Boolean),
    viewportHeight: window.innerHeight,
    scrollY: window.scrollY,
    pageHeight: document.documentElement.scrollHeight,
  })
}

/** Coalesce a burst of scroll events into one read per frame. */
function onScroll() {
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    syncToScroll()
  })
}

function go(id) {
  const target = document.getElementById(id)
  if (!target) return

  // Set it HERE rather than waiting for the scroll to report back. The click is
  // already an unambiguous answer, and a smooth scroll passes through every
  // section on the way — letting those win would flicker the highlight through
  // all of them before settling.
  active.value = id
  clickHoldsUntil = Date.now() + CLICK_HOLD_MS

  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => {
  syncToScroll()
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onScroll)
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onScroll)
  if (frame) cancelAnimationFrame(frame)
})
</script>

<template>
  <nav class="ui-secnav" aria-label="Page sections">
    <button
      v-for="s in sections"
      :key="s.id"
      type="button"
      class="ui-secnav__btn"
      :class="{ 'is-on': s.id === active }"
      :aria-current="s.id === active ? 'true' : undefined"
      @click="go(s.id)"
    >
      {{ s.label }}
    </button>
  </nav>
</template>

<style scoped>
.ui-secnav {
  position: fixed;
  left: 50%;
  bottom: max(18px, env(safe-area-inset-bottom));
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  gap: 2px;
  padding: 5px;
  border-radius: 999px;

  background: var(--ui-glass-mini-bg);
  -webkit-backdrop-filter: blur(28px) saturate(200%);
  backdrop-filter: blur(28px) saturate(200%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 0 0 1px rgba(255, 255, 255, 0.5),
    0 0 0 1px rgba(18, 18, 26, 0.07),
    0 18px 40px -18px rgba(18, 18, 26, 0.35),
    0 6px 14px -8px rgba(18, 18, 26, 0.18);

  /* Springs in on mount — the one entrance animation on the page. */
  animation: ui-dock 520ms var(--ui-spring) both;
  animation-delay: 200ms;
}

.ui-secnav__btn {
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--ui-muted);
  white-space: nowrap;
  transition:
    color var(--ui-fast) var(--ui-ease),
    background var(--ui-fast) var(--ui-ease),
    box-shadow var(--ui-fast) var(--ui-ease);
}

.ui-secnav__btn:hover {
  color: var(--ui-ink);
}

.ui-secnav__btn.is-on {
  color: #fff;
  background: var(--ui-action);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.22),
    0 2px 8px -2px rgba(79, 57, 246, 0.55);
}

@supports not (backdrop-filter: blur(1px)) {
  .ui-secnav {
    background: rgba(250, 250, 253, 0.98);
  }
}

@media (prefers-reduced-transparency: reduce) {
  .ui-secnav {
    background: #fafafd;
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ui-secnav {
    animation: none;
  }
}

@media (max-width: 560px) {
  .ui-secnav {
    max-width: calc(100vw - 24px);
    overflow-x: auto;
  }
}

@keyframes ui-dock {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(22px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}
</style>
