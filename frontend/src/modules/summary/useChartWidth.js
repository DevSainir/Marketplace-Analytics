/**
 * Measure a chart's own width so its SVG can be drawn in real pixels.
 *
 * The obvious alternative — a fixed `viewBox` scaled to 100 % width — is what
 * the first draft did, and it is why the charts looked blown up: at 1380px a
 * 800-unit viewBox magnifies everything 1.7×, including every label, so the
 * type no longer matches the type anywhere else on the page. Drawing at the
 * measured width keeps one unit equal to one pixel, which is the only way the
 * axis labels come out the size they are declared.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * @param {number} fallback Width to assume before the first measurement — used
 *   for the server-less first paint and when `ResizeObserver` is unavailable.
 * @returns {{el: import('vue').Ref<HTMLElement|null>, width: import('vue').Ref<number>}}
 */
export function useChartWidth(fallback = 720) {
  const el = ref(null)
  const width = ref(fallback)
  let observer = null

  onMounted(() => {
    if (!el.value) return
    const measure = () => {
      // A container collapsed to zero (a hidden tab, a page still laying out)
      // would otherwise produce a chart with a negative inner width and a pile
      // of NaN path commands.
      const measured = Math.round(el.value?.clientWidth ?? 0)
      if (measured > 0) width.value = measured
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    observer = new ResizeObserver(measure)
    observer.observe(el.value)
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { el, width }
}
