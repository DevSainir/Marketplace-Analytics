import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * «Two days on screen» held at REST, not only at load.
 *
 * The original ribbon opens on exactly two days and then lets a wheel or a drag
 * leave it anywhere — a third of one day, the whole of the next and two thirds
 * of a third. This settles the ribbon onto a day boundary once a gesture goes
 * quiet, and it settles FORWARD: in the direction the reader was already
 * moving. Rounding to the nearest boundary instead would swallow every small
 * gesture — one wheel click is 100px of a 600px day, and it would snap straight
 * back to where it began.
 *
 * Not CSS scroll-snap: `v-drag-scroll` drives `scrollLeft` from script, and a
 * mandatory snap container re-snaps every programmatic scroll too — the wheel
 * would never get past the day it started on.
 *
 * @param {object} options
 * @param {import('vue').Ref<HTMLElement|null>} options.scroll the ribbon's scroller
 * @param {() => number} options.step one day group plus the gap after it, in px
 * @param {() => number} options.count how many days the ribbon holds
 * @param {number} [options.perScreen] days a screen shows
 * @returns {{
 *   first: import('vue').Ref<number>,
 *   offset: import('vue').Ref<number>,
 *   go: (index: number) => void,
 * }}
 */
export function useDayPaging({ scroll, step, count, perScreen = 2 }) {
  /** Index of the leftmost day on screen. */
  const first = ref(0)
  /** `scrollLeft`, for whoever draws a seam once something is under the rail. */
  const offset = ref(0)

  const SETTLE_MS = 140
  // Fractional zoom leaves scroll positions a sub-pixel off any boundary.
  const EDGE_PX = 1
  let settled = 0
  let timer = null

  const lastFirst = () => Math.max(0, count() - perScreen)

  function settle() {
    const el = scroll.value
    const s = step()
    // Mid-drag the pointer owns the position; the release settles it.
    if (!el || s <= 0 || el.classList.contains('drag-scrolling')) return
    const x = el.scrollLeft
    const max = el.scrollWidth - el.clientWidth
    const nearest = Math.min(max, Math.round(x / s) * s)
    if (Math.abs(x - nearest) <= EDGE_PX || x >= max - EDGE_PX || x <= EDGE_PX) {
      settled = x
      return
    }
    const index = x > settled ? Math.ceil(x / s) : Math.floor(x / s)
    settled = Math.max(0, Math.min(max, index * s))
    el.scrollTo({ left: settled, behavior: 'smooth' })
  }

  function onScroll() {
    const el = scroll.value
    const s = step()
    offset.value = el.scrollLeft
    if (s > 0) first.value = Math.max(0, Math.min(lastFirst(), Math.round(el.scrollLeft / s)))
    clearTimeout(timer)
    timer = setTimeout(settle, SETTLE_MS)
  }

  /** A drag that stops dead fires no further scroll event to settle on. */
  function onRelease() {
    clearTimeout(timer)
    timer = setTimeout(settle, 0)
  }

  /** Put day `index` at the left of the screen (clamped so two always show). */
  function go(index) {
    const el = scroll.value
    const s = step()
    if (!el || s <= 0) return
    const target = Math.max(0, Math.min(lastFirst(), index)) * s
    settled = Math.min(el.scrollWidth - el.clientWidth, target)
    el.scrollTo({ left: settled, behavior: 'smooth' })
  }

  function bind(el) {
    el?.addEventListener('scroll', onScroll, { passive: true })
    el?.addEventListener('pointerup', onRelease)
    el?.addEventListener('pointercancel', onRelease)
  }

  function unbind(el) {
    el?.removeEventListener('scroll', onScroll)
    el?.removeEventListener('pointerup', onRelease)
    el?.removeEventListener('pointercancel', onRelease)
  }

  onMounted(() => bind(scroll.value))
  watch(scroll, (el, old) => {
    unbind(old)
    bind(el)
  })
  onBeforeUnmount(() => {
    clearTimeout(timer)
    unbind(scroll.value)
  })

  return { first, offset, go }
}
