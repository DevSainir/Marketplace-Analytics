/**
 * The scrolling half of a chart: how wide the plot is drawn, where it starts,
 * and the split between the pinned axis and the ribbon that moves.
 *
 * Extracted from `MetricsChartsPanel` because none of it is about the carousel
 * — it is the geometry of one plot, and keeping it in the component pushed the
 * component past the 250-line limit while burying the tab/slide logic that IS
 * specific to it.
 *
 * The shape mirrors the metrics table above: a wide ribbon scrolled sideways
 * (wheel, drag or trackpad, all via `v-drag-scroll`) with the labels that name
 * things held still beside it.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { DAY_WIDTH_PX, axisOnlyOption, plotOnlyOption } from '@/modules/labs/chartOptions'

/**
 * @param {import('vue').Ref<{option: object, dayCount: number, key: string}|null>} active
 *   The chart on screen. Its `key` changes whenever the question does — a new
 *   window, or a new set of metrics.
 * @returns {{
 *   scroller: import('vue').Ref<HTMLElement|null>,
 *   plotWidth: import('vue').ComputedRef<string>,
 *   axisOption: import('vue').ComputedRef<object|null>,
 *   plotOption: import('vue').ComputedRef<object|null>,
 * }}
 */
export function useChartRibbon(active) {
  const scroller = ref(null)

  // The chart decides how wide a day is — a long window draws them tighter so
  // more of it fits the card (see `dayWidthFor`).
  const plotWidth = computed(
    () => `${(active.value?.dayCount ?? 0) * (active.value?.dayWidth ?? DAY_WIDTH_PX)}px`,
  )

  // One chart, rendered twice: the axis stands still, the plot scrolls past it.
  const axisOption = computed(() =>
    active.value ? axisOnlyOption(active.value.option, active.value.axisGutter) : null,
  )
  const plotOption = computed(() => (active.value ? plotOnlyOption(active.value.option) : null))

  /** True once the reader has moved the ribbon themselves — then it is theirs. */
  let steered = false
  let observer = null

  /**
   * Open on the NEWEST day, the way the metrics table's ribbon does. History
   * runs off to the left; landing on a month-old Monday would make every chart
   * look like it was missing the data it actually has.
   */
  async function scrollToLatest() {
    await nextTick()
    const el = scroller.value
    if (el) el.scrollLeft = el.scrollWidth
  }

  /**
   * Re-pin whenever the ribbon's own width changes, until the reader steers.
   *
   * Once is not enough: at mount the flex row has not settled — the pinned
   * axis has not taken its column and the async chart has not loaded — so the
   * scroller measures wider than it ends up (1108px against a final 628px on
   * the «Графики» page). `scrollLeft = scrollWidth` clamps to the maximum THAT
   * width implies, which left the chart parked mid-window looking like the
   * recent days were missing.
   */
  function watchWidth() {
    const el = scroller.value
    if (!el || typeof ResizeObserver === 'undefined') return
    observer = new ResizeObserver(() => {
      if (!steered) scrollToLatest()
    })
    observer.observe(el)
  }

  /**
   * Hand the position over to the reader on their first real gesture.
   *
   * Bound to the INPUT events, not to `scroll`: a scroll event cannot tell a
   * finger from `scrollLeft = …`, so listening to it let the ribbon's own
   * opening scroll count as steering and cancel the re-pin that follows it.
   * A wheel or a pointer landing on the plot is unambiguously a person.
   */
  function onUserSteer() {
    steered = true
  }

  // A new question is asked of the last few days, so the ribbon goes back to
  // them — reader or no reader. Ticking a metric is a new question: it is asked
  // about how things are NOW, and answering it a fortnight back, wherever the
  // ribbon happened to be parked, hides the days the reader came for.
  watch(
    () => active.value?.key,
    () => {
      steered = false
      scrollToLatest()
    },
  )
  onMounted(() => {
    scrollToLatest()
    watchWidth()
  })
  onBeforeUnmount(() => observer?.disconnect())

  return { scroller, plotWidth, axisOption, plotOption, onUserSteer }
}
