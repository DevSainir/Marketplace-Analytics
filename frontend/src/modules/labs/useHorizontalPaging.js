/**
 * Sideways paging for a horizontally overflowing strip.
 *
 * The arrows only exist while the strip actually overflows, and each end's
 * arrow disables once that end is reached — so the control never offers a move
 * that would do nothing.
 *
 * Extracted from `PinnedSkuRow` because none of it is about pinned SKUs: it is
 * generic scroll-affordance bookkeeping (a ResizeObserver, two edge flags, and
 * a page step), and keeping it in the component buried the pin logic that IS
 * specific to it.
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

// Sub-pixel scroll positions never land exactly on 0 / max at fractional zoom
// levels, so treat anything within a pixel of an end as that end.
const EDGE_EPSILON_PX = 1

/**
 * @param {object} options
 * @param {() => unknown} options.contentSource Reactive source whose change
 *   can alter the strip's width (e.g. the item list). Re-measured on change.
 * @returns {{
 *   scroller: import('vue').Ref<HTMLElement|null>,
 *   overflowing: import('vue').Ref<boolean>,
 *   canScrollLeft: import('vue').Ref<boolean>,
 *   canScrollRight: import('vue').Ref<boolean>,
 *   page: (direction: number) => void,
 * }}
 */
export function useHorizontalPaging({ contentSource }) {
  const scroller = ref(null)
  const overflowing = ref(false)
  const canScrollLeft = ref(false)
  const canScrollRight = ref(false)

  function syncArrows() {
    const el = scroller.value
    if (!el) return
    const max = el.scrollWidth - el.clientWidth
    overflowing.value = max > EDGE_EPSILON_PX
    canScrollLeft.value = el.scrollLeft > EDGE_EPSILON_PX
    canScrollRight.value = el.scrollLeft < max - EDGE_EPSILON_PX
  }

  /** Page by most of a screenful, keeping a little context in view. */
  function page(direction) {
    const el = scroller.value
    if (!el) return
    el.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: 'smooth' })
  }

  let observer = null

  onMounted(() => {
    syncArrows()
    // Overflow changes with the viewport, not just with the content.
    observer = new ResizeObserver(syncArrows)
    if (scroller.value) observer.observe(scroller.value)
  })

  onBeforeUnmount(() => observer?.disconnect())

  watch(contentSource, () => nextTick(syncArrows), { deep: true })

  return { scroller, overflowing, canScrollLeft, canScrollRight, page, syncArrows }
}
