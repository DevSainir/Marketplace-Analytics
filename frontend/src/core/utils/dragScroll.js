/**
 * Mouse-friendly scrolling for wide table ribbons: vertical wheel input scrolls
 * the container HORIZONTALLY (mouse users have no shift-wheel reflex for a
 * sideways table), and holding the left button drags/pans it.
 *
 * Vue directive shape (`v-drag-scroll`) so components attach it declaratively
 * to their scroll container. Behavior details:
 *
 * - Wheel: only plain vertical wheel input is translated (trackpads emit real
 *   deltaX and keep native behavior). While the cursor is over a ribbon that
 *   CAN scroll sideways the gesture is always consumed — including at either
 *   edge, so reading to the end of a table never hands the wheel back to the
 *   page and yanks it out from under the reader.
 * - Drag: starts only after a small threshold so cell clicks (inline editing)
 *   stay clicks; a real drag suppresses the click that would otherwise fire on
 *   release. Dragging from an input/textarea is ignored (text selection).
 */

const DRAG_THRESHOLD_PX = 4

function onWheel(event) {
  const el = event.currentTarget
  if (event.deltaX !== 0 || event.deltaY === 0 || event.ctrlKey) return // native
  const max = el.scrollWidth - el.clientWidth
  if (max <= 0) return // nothing to scroll sideways: leave the page alone
  el.scrollLeft = Math.max(0, Math.min(max, el.scrollLeft + event.deltaY))
  // Always consume it: the ribbon owns vertical wheel input for as long as the
  // cursor is over it. Releasing the gesture at the edges would scroll the page
  // mid-read, which is exactly what a reader panning a wide table does not want.
  event.preventDefault()
}

function onPointerDown(event) {
  if (event.button !== 0 || event.pointerType !== 'mouse') return
  if (event.target.closest('input, textarea')) return // keep text selection
  const el = event.currentTarget
  const state = el.__dragScroll
  state.startX = event.clientX
  state.startY = event.clientY
  state.startLeft = el.scrollLeft
  state.startTop = el.scrollTop
  state.active = true
  state.dragged = false
}

function onPointerMove(event) {
  const el = event.currentTarget
  const state = el.__dragScroll
  if (!state.active) return
  const dx = event.clientX - state.startX
  const dy = event.clientY - state.startY
  if (!state.dragged) {
    if (Math.abs(dx) < DRAG_THRESHOLD_PX && Math.abs(dy) < DRAG_THRESHOLD_PX) return
    state.dragged = true
    el.setPointerCapture(event.pointerId)
    el.classList.add('drag-scrolling')
  }
  el.scrollLeft = state.startLeft - dx
  el.scrollTop = state.startTop - dy
}

function onPointerUp(event) {
  const el = event.currentTarget
  const state = el.__dragScroll
  if (state.dragged && el.hasPointerCapture(event.pointerId)) {
    el.releasePointerCapture(event.pointerId)
  }
  state.active = false
  el.classList.remove('drag-scrolling')
}

function onClickCapture(event) {
  const state = event.currentTarget.__dragScroll
  if (!state.dragged) return
  // The pointer travelled: this "click" was a drag — swallow it so a cell
  // under the cursor doesn't switch into edit mode.
  state.dragged = false
  event.preventDefault()
  event.stopPropagation()
}

/** `v-drag-scroll` — attach wheel-to-horizontal + LMB drag-pan to an element. */
export const vDragScroll = {
  mounted(el) {
    el.__dragScroll = { active: false, dragged: false }
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('pointerdown', onPointerDown)
    el.addEventListener('pointermove', onPointerMove)
    el.addEventListener('pointerup', onPointerUp)
    el.addEventListener('pointercancel', onPointerUp)
    el.addEventListener('click', onClickCapture, true)
  },
  unmounted(el) {
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('pointerdown', onPointerDown)
    el.removeEventListener('pointermove', onPointerMove)
    el.removeEventListener('pointerup', onPointerUp)
    el.removeEventListener('pointercancel', onPointerUp)
    el.removeEventListener('click', onClickCapture, true)
    delete el.__dragScroll
  },
}
