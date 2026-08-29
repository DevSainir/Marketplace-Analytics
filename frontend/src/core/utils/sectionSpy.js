/**
 * Which section of a long page is currently being read.
 *
 * Split out of `SectionNav.vue` so the decision can be tested against positions
 * directly. The component's job is then only to read those positions off the DOM
 * and hand them over — which is the half a browser is needed for.
 */

/**
 * Where on the screen a section counts as «the one being read», as a fraction of
 * the viewport. Near the top, because a section becomes current when its heading
 * arrives, not when it reaches the middle.
 */
export const READING_LINE = 0.3

/**
 * Return the id of the section the reader is in: the last one that has started.
 *
 * @param {object} view
 * @param {Array<{id: string, top: number}>} view.sections in page order, each
 *   with its viewport-relative top (what `getBoundingClientRect` reports)
 * @param {number} view.viewportHeight
 * @param {number} view.scrollY
 * @param {number} view.pageHeight total scrollable height of the document
 * @param {number} [view.readingLine] override for {@link READING_LINE}
 * @returns {string|null} the active section id, or `null` when there are none
 */
export function currentSectionId({
  sections,
  viewportHeight,
  scrollY,
  pageHeight,
  readingLine = READING_LINE,
}) {
  if (!sections?.length) return null

  const line = viewportHeight * readingLine
  let current = sections[0].id
  for (const section of sections) {
    if (section.top <= line) current = section.id
  }

  // The bottom of the page is its own case. A short last section can sit below
  // the reading line with nowhere left to scroll, so it would never become
  // current however far down you are — and «the end of the page» is the one
  // moment you are certainly in the last section.
  if (viewportHeight + scrollY >= pageHeight - 2) {
    current = sections[sections.length - 1].id
  }

  return current
}
