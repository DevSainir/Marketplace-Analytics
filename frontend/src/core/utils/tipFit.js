/**
 * Keep a floating tip inside the table it explains — the rule for every hint,
 * name tip and breakdown popup on a table in the app.
 *
 * Tips are teleported to `<body>` (a scroll container would clip them), which
 * frees them from the table entirely: placed only against the viewport, a
 * header hint at the table's right edge hung past the card's rounded corner
 * over the page. So the anchor's VISIBLE area is measured — the viewport cut
 * by every scrolling or clipping ancestor, i.e. exactly the part of the table
 * on screen — and the bubble is slid back inside it, and narrowed if the area
 * is narrower than the bubble.
 *
 * Horizontal only: each tip already decides between below and above its
 * anchor, and the complaint was never vertical.
 *
 * Usage: take `visibleArea(anchorElement)` when the tip opens, keep it on the
 * tip's state, and put `v-fit-inside="tip.area"` on the bubble.
 */

/** Air between the bubble and the edge it is kept from. */
const EDGE_GAP_PX = 8

/** Does this element cut off what overflows it? */
function clips(el) {
  const { overflowX, overflowY } = getComputedStyle(el)
  return [overflowX, overflowY].some((value) => value !== 'visible')
}

/**
 * The part of the screen through which `el` can be seen: the viewport
 * narrowed by each clipping ancestor. A plain `{left, right}` — the rect is
 * taken once, when the tip opens, and tips close on scroll.
 *
 * @param {Element|null} el The tip's anchor.
 * @returns {{left: number, right: number}}
 */
export function visibleArea(el) {
  const area = { left: 0, right: window.innerWidth }
  for (let node = el?.parentElement; node && node !== document.body; node = node.parentElement) {
    if (!clips(node)) continue
    const rect = node.getBoundingClientRect()
    area.left = Math.max(area.left, rect.left)
    area.right = Math.min(area.right, rect.right)
  }
  return area
}

/**
 * Slide (and if need be narrow) a rendered bubble so it sits inside `area`.
 * Uses `translate` and `max-width`, which nothing else on a tip sets, so the
 * caller's own `left` and `transform` are left alone and the fit can be redone
 * from scratch on every update.
 *
 * @param {HTMLElement} el The bubble.
 * @param {{left: number, right: number}|null} area From `visibleArea`; the viewport when absent.
 */
export function fitInside(el, area) {
  const bounds = area ?? { left: 0, right: window.innerWidth }
  const room = Math.max(0, bounds.right - bounds.left - 2 * EDGE_GAP_PX)
  el.style.translate = ''
  el.style.maxWidth = `${room}px`
  const rect = el.getBoundingClientRect()
  const min = bounds.left + EDGE_GAP_PX
  const max = bounds.right - EDGE_GAP_PX
  let shift = 0
  if (rect.right > max) shift = max - rect.right
  if (rect.left + shift < min) shift = min - rect.left
  el.style.translate = shift ? `${shift}px 0` : ''
}

/** `v-fit-inside="area"` — `fitInside` on mount and after every re-render. */
export const vFitInside = {
  mounted: (el, binding) => fitInside(el, binding.value),
  updated: (el, binding) => fitInside(el, binding.value),
}
