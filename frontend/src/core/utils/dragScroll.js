/**
 * Mouse-friendly scrolling for wide table ribbons: vertical wheel input scrolls
 * the container HORIZONTALLY (mouse users have no shift-wheel reflex for a
 * sideways table), and holding the left button drags/pans it.
 *
 * Vue directive shape (`v-drag-scroll`) so components attach it declaratively
 * to their scroll container. Behavior details:
 *
 * - Mouse wheel: vertical input is translated to horizontal. While the cursor is
 *   over a ribbon that CAN scroll sideways the gesture is always consumed —
 *   including at either edge, so reading to the end of a table never hands the
 *   wheel back to the page and yanks it out from under the reader.
 * - Trackpad: kept native, but axis-locked. A two-finger swipe is never purely
 *   vertical — it leaks a few px of deltaX, and it also emits plenty of frames
 *   with deltaX exactly 0. Left alone, the first kind pans the ribbon a pixel at
 *   a time and the second kind hits the wheel-to-horizontal path above: the
 *   table twitches sideways while the page scrolls down. So a gesture that
 *   starts out vertical pins the ribbon (`overflow-x: hidden` via
 *   `.wheel-axis-locked`) until the gesture ends; a sideways one scrolls
 *   natively, momentum and all.
 * - Drag: starts only after a small threshold so cell clicks (inline editing)
 *   stay clicks; a real drag suppresses the click that would otherwise fire on
 *   release. Dragging from an input/textarea is ignored (text selection).
 */

const DRAG_THRESHOLD_PX = 4
/** Class the ribbon wears while a vertical trackpad gesture owns the screen. */
const AXIS_LOCK_CLASS = 'wheel-axis-locked'
/** A wheel gesture is over once it has gone quiet this long. Generous, because
 *  macOS momentum keeps firing events well past the finger lift. */
const GESTURE_END_MS = 200
/** Lock sideways scrolling only when the gesture is decidedly not sideways —
 *  a near-diagonal swipe stays free so a real pan is never swallowed. */
const VERTICAL_DOMINANCE = 1.5

/**
 * Trackpad or wheel? Nothing reports this directly, so it is read off the shape
 * of the delta: a wheel turns in coarse whole clicks with no sideways
 * component, a trackpad glides.
 */
function isTrackpad(event) {
  if (event.deltaMode !== 0) return false // Firefox measures a real wheel in lines
  if (event.deltaX !== 0) return true
  if (!Number.isInteger(event.deltaY)) return true
  // WebKit/Blink only: one wheel click is always a multiple of 120 here.
  if (event.wheelDeltaY) return Math.abs(event.wheelDeltaY) % 120 !== 0
  return false
}

/**
 * Hold the ribbon still for a vertical trackpad gesture. The lock lands one
 * frame late (the class only takes effect after this handler returns), so the
 * position is also restored on the next event to swallow that first stray pixel.
 */
function applyAxisLock(el, state, event) {
  if (state.axis === null) {
    const dx = Math.abs(event.deltaX)
    const dy = Math.abs(event.deltaY)
    if (dx === 0 && dy === 0) return
    state.axis = dy > dx * VERTICAL_DOMINANCE ? 'y' : 'x'
  }
  if (state.axis !== 'y') return
  if (!el.classList.contains(AXIS_LOCK_CLASS)) {
    state.lockedLeft = el.scrollLeft
    el.classList.add(AXIS_LOCK_CLASS)
  } else if (el.scrollLeft !== state.lockedLeft) {
    el.scrollLeft = state.lockedLeft
  }
}

function endWheelGesture(el) {
  const state = el.__dragScroll
  state.trackpad = false
  state.axis = null
  el.classList.remove(AXIS_LOCK_CLASS)
}

function onWheel(event) {
  if (event.ctrlKey) return // pinch-zoom belongs to the browser
  const el = event.currentTarget
  const state = el.__dragScroll
  const max = el.scrollWidth - el.clientWidth
  if (max <= 0) return // nothing to scroll sideways: leave the page alone

  // One trackpad frame marks the whole gesture: the sideways component of a
  // swipe comes and goes, and the frames where it is 0 must not be mistaken for
  // wheel clicks.
  if (isTrackpad(event)) state.trackpad = true
  clearTimeout(state.gestureEnd)
  state.gestureEnd = setTimeout(() => endWheelGesture(el), GESTURE_END_MS)

  if (state.trackpad) {
    applyAxisLock(el, state, event)
    return // native scrolling, on whichever axis survived the lock
  }

  if (event.deltaY === 0) return
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
    el.__dragScroll = {
      active: false,
      dragged: false,
      trackpad: false,
      axis: null,
      lockedLeft: 0,
      gestureEnd: null,
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('pointerdown', onPointerDown)
    el.addEventListener('pointermove', onPointerMove)
    el.addEventListener('pointerup', onPointerUp)
    el.addEventListener('pointercancel', onPointerUp)
    el.addEventListener('click', onClickCapture, true)
  },
  unmounted(el) {
    clearTimeout(el.__dragScroll.gestureEnd)
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('pointerdown', onPointerDown)
    el.removeEventListener('pointermove', onPointerMove)
    el.removeEventListener('pointerup', onPointerUp)
    el.removeEventListener('pointercancel', onPointerUp)
    el.removeEventListener('click', onClickCapture, true)
    delete el.__dragScroll
  },
}
