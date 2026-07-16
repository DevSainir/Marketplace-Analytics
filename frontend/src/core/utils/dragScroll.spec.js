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
