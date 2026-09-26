import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * The «Остатки по складам» ribbon's viewport arithmetic: how wide one day is,
 * and which day it opens on.
 *
 * Extracted from `StockCompareTable.vue` when that file reached the 250-line
 * component ceiling. It is also the part of the grid that is not about markup
 * at all — it is a measurement, an observer and two watches, and reading it
 * next to the template made both harder to follow.
 *
 * The measurement exists because the day groups hold different numbers of
 * columns (each day shows only the warehouses it stocked) and a table divides
 * its width per COLUMN — so the widths come from a `<colgroup>`, in px, and
 * something has to know what a day group's px are. See the component.
 *
 * @param {object} options
 * @param {() => unknown} options.daysSource Reactive source of the rendered
 *   days; a change re-opens the ribbon on the newest one.
 * @param {() => number} [options.perScreen] How many day groups one screen
 *   holds (2 unless the grid says otherwise); a change re-measures.
 * @returns {{
 *   root: import('vue').Ref<HTMLElement|null>,
 *   scroll: import('vue').Ref<HTMLElement|null>,
 *   groupWidth: import('vue').Ref<number|null>,
 * }}
 */
export function useStockRibbonLayout({ daysSource, perScreen = () => 2 }) {
  const root = ref(null)
  const scroll = ref(null)
  /**
   * Half of what the frozen size column leaves — one day group, in px.
   *
   * `null` until it has actually been measured, which is NOT the same as zero:
   * zero collapses every warehouse column to nothing (the `<colgroup>` divides
   * this between them), so an unmeasured grid must fall back to the
   * stylesheet's default instead of emitting a width of 0.
   */
  const groupWidth = ref(null)

  /** Read a px-valued custom property off the grid (they are px so this can). */
  function cssPx(name) {
    return parseFloat(getComputedStyle(root.value).getPropertyValue(name)) || 0
  }

  function measure() {
    if (!scroll.value || !root.value) return
    const measured = (scroll.value.clientWidth - cssPx('--col-size-w')) / perScreen()
    // A container with no width yet (a hidden tab, a pane not laid out) measures
    // zero; keeping the last known width beats collapsing the grid.
    if (measured > 0) groupWidth.value = measured
  }

  /** Start at the right edge: «сегодня» first, older days appear scrolling left. */
  function scrollToNewestDay() {
    if (scroll.value) scroll.value.scrollLeft = scroll.value.scrollWidth
  }

  let observer = null

  /**
   * (Re)attach to the scroll container and measure it.
   *
   * The container is behind a `v-if` on there being any stock, and the stock
   * arrives in its own request AFTER the component mounts — so at mount there
   * is usually nothing to observe. Measuring only there left the width at zero
   * for the life of the page: every warehouse column divided zero between them
   * and vanished, leaving a grid of «Всего» columns.
   */
  function attach() {
    observer?.disconnect()
    if (!scroll.value) return
    observer?.observe(scroll.value)
    measure()
    scrollToNewestDay()
  }

  onMounted(() => {
    // The group is half the VIEWPORT's share, so it moves with the window as
    // well as with the data.
    observer = new ResizeObserver(measure)
    attach()
  })

  onBeforeUnmount(() => observer?.disconnect())

  // The container appears (and is replaced) as the stock comes and goes.
  watch(scroll, () => nextTick(attach))

  // The days, and the measurement that decides how wide they are — the ribbon
  // can only land on «сегодня» once the width it scrolls across is real.
  watch([daysSource, groupWidth], () => nextTick(scrollToNewestDay))

  watch(perScreen, () => nextTick(measure))

  return { root, scroll, groupWidth }
}
