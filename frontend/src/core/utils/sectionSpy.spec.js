import { describe, expect, it } from 'vitest'

import { currentSectionId } from '@/core/utils/sectionSpy'

/**
 * The scrollspy's decision, pinned against positions.
 *
 * It replaced an IntersectionObserver, and these are the cases that observer got
 * wrong: a section shorter than the watched band never lit, and the last section
 * on the page could not reach the band at all.
 */
const view = (tops, { viewportHeight = 1000, scrollY = 0, pageHeight = 9999 } = {}) => ({
  sections: tops.map(([id, top]) => ({ id, top })),
  viewportHeight,
  scrollY,
  pageHeight,
})

describe('currentSectionId', () => {
  it('is the first section at the top of the page', () => {
    const state = view([
      ['a', 200],
      ['b', 1400],
      ['c', 2600],
    ])

    expect(currentSectionId(state)).toBe('a')
  })

  it('advances once a section crosses the reading line', () => {
    // The line is 30% of a 1000px viewport, so 300. `b` has started; `c` has not.
    const state = view([
      ['a', -900],
      ['b', 280],
      ['c', 1500],
    ])

    expect(currentSectionId(state)).toBe('b')
  })

  it('takes the LAST section that has started, not the first', () => {
    // Several can be above the line at once on a page of short sections; the one
    // being read is the most recent, not the earliest.
    const state = view([
      ['a', -2000],
      ['b', -900],
      ['c', 100],
    ])

    expect(currentSectionId(state)).toBe('c')
  })

  it('holds the first section until one actually starts', () => {
    const state = view([
      ['a', 400],
      ['b', 1600],
    ])

    expect(currentSectionId(state)).toBe('a')
  })

  it('selects the last section at the bottom of the page', () => {
    // The case the observer could never handle: `c` is short and sits below the
    // reading line with nowhere left to scroll, so it would otherwise never be
    // current no matter how far down the reader is.
    const state = view(
      [
        ['a', -3000],
        ['b', -1200],
        ['c', 700],
      ],
      {
        viewportHeight: 1000,
        scrollY: 4000,
        pageHeight: 5000,
      },
    )

    expect(currentSectionId(state)).toBe('c')
  })

  it('does not claim the bottom case while the page still scrolls', () => {
    const state = view(
      [
        ['a', -3000],
        ['b', -1200],
        ['c', 700],
      ],
      {
        viewportHeight: 1000,
        scrollY: 2000,
        pageHeight: 9000,
      },
    )

    expect(currentSectionId(state)).toBe('b')
  })

  it('returns null when there are no sections', () => {
    expect(
      currentSectionId({ sections: [], viewportHeight: 900, scrollY: 0, pageHeight: 900 }),
    ).toBe(null)
  })
})
