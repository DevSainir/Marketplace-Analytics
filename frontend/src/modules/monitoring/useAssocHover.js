/**
 * The associative-conversion hover behind the carts/orders cells.
 *
 * Those cells show a campaign's ALL-VARIANT total. Hovering one reports the
 * ASSOCIATED share of that total — what the campaign delivered onto other
 * size/colour variants — and names them. An always-visible breakdown would
 * clutter thousands of cells, so it is a hover.
 *
 * The "Overall" CTR cell rides the same listener: its "Clicks" row is the
 * funnel's, so the hover names the advertising clicks and views the CTR
 * actually divides (`ctrTip`).
 *
 * Delegated: ONE mouseover listener on the scroll container, with cells
 * carrying their index key in `data-assoc`. Attaching a listener per cell would
 * mean thousands of them on a grid this size.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { visibleArea } from '@/core/utils/tipFit'
import { formatNumber, formatPercent, formatSku } from '@/core/utils/format'

const ASSOC_METRICS = new Set(['carts', 'orders'])

/** The cell's hover payload, or null: a carts/orders breakdown or a CTR basis. */
function hoverPayload(row, cell) {
  if (ASSOC_METRICS.has(row.key)) return cell?.assoc ? cell : null
  return row.key === 'ctr' && cell?.ctrBasis ? cell : null
}

/** Room for the tallest breakdown; nearer the viewport floor the tip flips above. */
const ASSOC_TIP_MAX_HEIGHT_PX = 260

/** Both tips are `w-72`; a cell nearer the right edge pulls its tip left. */
const TIP_WIDTH_PX = 288
const TIP_EDGE_GAP_PX = 8

/**
 * @param {() => Array<{key: string, cells: object[]}>} rows Reactive accessor
 *   for the metric rows currently rendered.
 */
export function useAssocHover(rows) {
  const assocTip = ref(null) // { x, y, above, associated, exact, skus } | null
  const ctrTip = ref(null) // { x, y, above, clicks, views, ctr } | null

  // Cell -> hover payload, keyed by the `data-assoc` attribute. Follows the
  // rows, so an edit to the SKU's own slice keeps the associated remainder in
  // step.
  const assocIndex = computed(() => {
    const index = new Map()
    for (const row of rows()) {
      for (const cell of row.cells) {
        if (hoverPayload(row, cell)) index.set(`${row.key}|${cell.day}|${cell.bucket}`, cell)
      }
    }
    return index
  })

  /** `data-assoc` key for a cell, or null (attribute omitted -> no hover). */
  function assocData(row, cell) {
    if (!hoverPayload(row, cell)) return null
    return `${row.key}|${cell.day}|${cell.bucket}`
  }

  function onMatrixOver(event) {
    const el = event.target.closest('[data-assoc]')
    const cell = el ? assocIndex.value.get(el.dataset.assoc) : null
    if (!cell) {
      hideAssocTip()
      return
    }
    const rect = el.getBoundingClientRect()
    const above = rect.bottom + ASSOC_TIP_MAX_HEIGHT_PX > window.innerHeight
    // "Overall" sits at the ribbon's right edge on the newest day — keep the tip on screen.
    const x = Math.max(
      TIP_EDGE_GAP_PX,
      Math.min(rect.left, window.innerWidth - TIP_WIDTH_PX - TIP_EDGE_GAP_PX),
    )
    const place = { x, y: above ? rect.top - 6 : rect.bottom + 6, above, area: visibleArea(el) }
    if (cell.ctrBasis) {
      assocTip.value = null
      ctrTip.value = {
        ...place,
        clicks: formatNumber(cell.ctrBasis.clicks),
        views: formatNumber(cell.ctrBasis.views),
        clickCount: cell.ctrBasis.clicks,
        viewCount: cell.ctrBasis.views,
        ctr: formatPercent(cell.raw),
      }
      return
    }
    ctrTip.value = null
    assocTip.value = {
      ...place,
      associated: formatNumber(cell.assoc.associated),
      exact: cell.assoc.exact,
      skus: cell.assoc.skus.map((sku) => ({
        key: sku.nm_id,
        label: formatSku(sku.vendor_code) || `nm ${sku.nm_id}`,
        count: formatNumber(sku.count),
        isViewed: sku.isViewed,
      })),
    }
  }

  function hideAssocTip() {
    assocTip.value = null
    ctrTip.value = null
  }

  onMounted(() => {
    // Any scroll strands the fixed-position tip — close it (capture catches the
    // ribbon's own scroll container too).
    document.addEventListener('scroll', hideAssocTip, true)
  })
  onBeforeUnmount(() => document.removeEventListener('scroll', hideAssocTip, true))

  return { assocTip, ctrTip, assocData, onMatrixOver, hideAssocTip }
}
