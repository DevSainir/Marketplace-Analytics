/**
 * The associative-conversion hover behind the carts/orders cells.
 *
 * Those cells show a campaign's ALL-VARIANT total. Hovering one reports the
 * ASSOCIATED share of that total — what the campaign delivered onto other
 * size/colour variants — and names them. An always-visible breakdown would
 * clutter thousands of cells, so it is a hover.
 *
 * Delegated: ONE mouseover listener on the scroll container, with cells
 * carrying their index key in `data-assoc`. Attaching a listener per cell would
 * mean thousands of them on a grid this size.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { formatNumber } from '@/core/utils/format'

const ASSOC_METRICS = new Set(['carts', 'orders'])

/** Room for the tallest breakdown; nearer the viewport floor the tip flips above. */
const ASSOC_TIP_MAX_HEIGHT_PX = 260

/**
 * @param {() => Array<{key: string, cells: object[]}>} rows Reactive accessor
 *   for the metric rows currently rendered.
 */
export function useAssocHover(rows) {
  const assocTip = ref(null) // { x, y, above, associated, exact, skus } | null

  // Cell -> hover payload, keyed by the `data-assoc` attribute. Follows the
  // rows, so an edit to the SKU's own slice keeps the associated remainder in
  // step.
  const assocIndex = computed(() => {
    const index = new Map()
    for (const row of rows()) {
      if (!ASSOC_METRICS.has(row.key)) continue
      for (const cell of row.cells) {
        if (cell?.assoc) index.set(`${row.key}|${cell.day}|${cell.bucket}`, cell)
      }
    }
    return index
  })

  /** `data-assoc` key for a cell, or null (attribute omitted -> no hover). */
  function assocData(row, cell) {
    if (!ASSOC_METRICS.has(row.key) || !cell.assoc) return null
    return `${row.key}|${cell.day}|${cell.bucket}`
  }

  function onMatrixOver(event) {
    const el = event.target.closest('[data-assoc]')
    const cell = el ? assocIndex.value.get(el.dataset.assoc) : null
    if (!cell) {
      assocTip.value = null
      return
    }
    const rect = el.getBoundingClientRect()
    const above = rect.bottom + ASSOC_TIP_MAX_HEIGHT_PX > window.innerHeight
    assocTip.value = {
      x: rect.left,
      y: above ? rect.top - 6 : rect.bottom + 6,
      above,
      associated: formatNumber(cell.assoc.associated),
      exact: cell.assoc.exact,
      skus: cell.assoc.skus.map((sku) => ({
        key: sku.nm_id,
        label: sku.vendor_code || `nm ${sku.nm_id}`,
        count: formatNumber(sku.count),
        isViewed: sku.isViewed,
      })),
    }
  }

  function hideAssocTip() {
    assocTip.value = null
  }

  onMounted(() => {
    // Any scroll strands the fixed-position tip — close it (capture catches the
    // ribbon's own scroll container too).
    document.addEventListener('scroll', hideAssocTip, true)
  })
  onBeforeUnmount(() => document.removeEventListener('scroll', hideAssocTip, true))

  return { assocTip, assocData, onMatrixOver, hideAssocTip }
}
