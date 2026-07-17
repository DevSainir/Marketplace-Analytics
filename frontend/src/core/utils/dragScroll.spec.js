import { vDragScroll } from '@/core/utils/dragScroll'

/**
 * A scrollable stand-in for a table ribbon. jsdom gives no layout, so
 * scrollWidth/clientWidth are defined here and scrollLeft is clamped the way a
 * real container clamps it.
 */
function ribbon({ scrollWidth = 1000, clientWidth = 200, scrollLeft = 0 } = {}) {
  const el = document.createElement('div')
  Object.defineProperty(el, 'scrollWidth', { value: scrollWidth })
  Object.defineProperty(el, 'clientWidth', { value: clientWidth })
  let position = scrollLeft
  Object.defineProperty(el, 'scrollLeft', {
    get: () => position,
    set: (value) => {
      position = Math.max(0, Math.min(scrollWidth - clientWidth, value))
    },
  })
  document.body.appendChild(el)
  vDragScroll.mounted(el)
  return el
}

/** Wheel the element and report whether the handler swallowed the gesture. */
function wheel(el, { deltaY, deltaX = 0, ctrlKey = false } = {}) {
  const event = new WheelEvent('wheel', { deltaY, deltaX, ctrlKey, cancelable: true })
  el.dispatchEvent(event)
  return event.defaultPrevented
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('v-drag-scroll wheel handling', () => {
  it('turns vertical wheel input into horizontal scrolling', () => {
    const el = ribbon()
    expect(wheel(el, { deltaY: 120 })).toBe(true)
    expect(el.scrollLeft).toBe(120)
  })

  // The point of the directive: while the cursor is over a sideways-scrolling
  // ribbon, the wheel belongs to the ribbon. Handing the gesture back at the
  // edges would scroll the page out from under someone reading the table.
  it('keeps consuming the wheel at the right edge', () => {
    const el = ribbon({ scrollLeft: 800 }) // already at max (1000 - 200)
    expect(wheel(el, { deltaY: 120 })).toBe(true)
    expect(el.scrollLeft).toBe(800)
  })

  it('keeps consuming the wheel at the left edge', () => {
    const el = ribbon({ scrollLeft: 0 })
    expect(wheel(el, { deltaY: -120 })).toBe(true)
    expect(el.scrollLeft).toBe(0)
  })

  it('leaves the page alone when there is nothing to scroll sideways', () => {
    const el = ribbon({ scrollWidth: 200, clientWidth: 200 })
    expect(wheel(el, { deltaY: 120 })).toBe(false)
  })

  it('passes trackpad and zoom gestures through untouched', () => {
    const el = ribbon()
    expect(wheel(el, { deltaY: 120, deltaX: 40 })).toBe(false) // trackpad pan
    expect(wheel(el, { deltaY: 120, ctrlKey: true })).toBe(false) // pinch-zoom
    expect(el.scrollLeft).toBe(0)
  })
})

// A two-finger vertical swipe leaks a little deltaX and also emits frames with
// no deltaX at all. Both used to move the ribbon sideways — the twitch.
describe('v-drag-scroll trackpad axis lock', () => {
  it('pins the ribbon once a swipe reads as vertical', () => {
    const el = ribbon()
    wheel(el, { deltaY: 12, deltaX: 1 })
    expect(el.classList.contains('wheel-axis-locked')).toBe(true)
  })

  it('does not translate the deltaX-free frames of a vertical swipe', () => {
    const el = ribbon()
    wheel(el, { deltaY: 12, deltaX: 1 }) // marks the gesture as trackpad
    expect(wheel(el, { deltaY: 40 })).toBe(false) // a wheel click would be consumed
    expect(el.scrollLeft).toBe(0)
  })

  it('undoes the pixel that leaks past the lock before it takes effect', () => {
    const el = ribbon({ scrollLeft: 300 })
    wheel(el, { deltaY: 12, deltaX: 1 })
    el.scrollLeft = 302 // the browser applied that first frame's deltaX natively
    wheel(el, { deltaY: 14, deltaX: 1 })
    expect(el.scrollLeft).toBe(300)
  })

  it('leaves a sideways swipe alone', () => {
    const el = ribbon()
    wheel(el, { deltaY: 1, deltaX: 20 })
    expect(el.classList.contains('wheel-axis-locked')).toBe(false)
    // Still vertical-ish frames later in the gesture must not flip the lock on.
    wheel(el, { deltaY: 12, deltaX: 1 })
    expect(el.classList.contains('wheel-axis-locked')).toBe(false)
  })

  it('releases the lock once the gesture goes quiet', async () => {
    vi.useFakeTimers()
    const el = ribbon()
    wheel(el, { deltaY: 12, deltaX: 1 })
    vi.advanceTimersByTime(500)
    expect(el.classList.contains('wheel-axis-locked')).toBe(false)
    // A wheel click after the gesture pans the ribbon again.
    expect(wheel(el, { deltaY: 120 })).toBe(true)
    expect(el.scrollLeft).toBe(120)
    vi.useRealTimers()
  })
})
