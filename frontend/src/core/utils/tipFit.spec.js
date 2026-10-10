import { afterEach, describe, expect, it } from 'vitest'

import { fitInside, visibleArea } from '@/core/utils/tipFit'

/**
 * jsdom has no layout, so each box is given the rect a browser would report.
 * A bubble's rect follows its `translate`, the way a real one moves.
 */
function box({ left, width, overflow = 'visible', parent = document.body }) {
  const el = document.createElement('div')
  // Both longhands: jsdom does not expand the `overflow` shorthand.
  el.style.overflowX = overflow
  el.style.overflowY = overflow
  el.getBoundingClientRect = () => {
    const shift = parseFloat(el.style.translate) || 0
    return { left: left + shift, right: left + shift + width, width }
  }
  parent.appendChild(el)
  return el
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('visibleArea', () => {
  it('is the scrolling table, not the viewport, around a header hint', () => {
    // Arrange: a card scroller 600px wide, a header cell inside it
    const scroller = box({ left: 40, width: 600, overflow: 'auto' })
    const header = box({ left: 500, width: 120, parent: scroller })
    const hint = box({ left: 600, width: 14, parent: header })

    // Act
    const area = visibleArea(hint)

    // Assert
    expect(area).toEqual({ left: 40, right: 640 })
  })

  it('is cut by every clipping ancestor, the narrowest edge winning', () => {
    const outer = box({ left: 0, width: 700, overflow: 'auto' })
    const inner = box({ left: 100, width: 900, overflow: 'hidden', parent: outer })
    const hint = box({ left: 300, width: 14, parent: inner })

    expect(visibleArea(hint)).toEqual({ left: 100, right: 700 })
  })
})

describe('fitInside', () => {
  it('slides a bubble that hangs past the right edge back inside', () => {
    // Arrange: the screenshot's case — a 288px bubble at x=500 in a table ending at 640
    const bubble = box({ left: 500, width: 288 })

    // Act
    fitInside(bubble, { left: 40, right: 640 })

    // Assert: right edge sits 8px inside the table
    expect(bubble.getBoundingClientRect().right).toBe(632)
  })

  it('leaves a bubble that already fits where it is', () => {
    const bubble = box({ left: 100, width: 200 })

    fitInside(bubble, { left: 40, right: 640 })

    expect(bubble.style.translate).toBe('')
  })

  it('never lets the area be narrower than the bubble', () => {
    const bubble = box({ left: 0, width: 100 })

    fitInside(bubble, { left: 0, right: 200 })

    expect(bubble.style.maxWidth).toBe('184px')
  })
})
