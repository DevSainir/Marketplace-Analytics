/**
 * The metrics matrix draws its day and campaign dividers with `nth-child`
 * strides, and two stylesheets state them: `assets/main.css` adds the 2px
 * borders, the `ui-next` skin recolours them. When the unified «Каталог»
 * column went, main.css moved to the new strides and the skin kept the old
 * ones, so from the sixth day on a campaign seam was painted as a black day
 * boundary. Both files are checked against the column model here.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { COLUMNS_PER_DAY, TRAFFIC_GROUPS } from '@/modules/monitoring/metricsMatrix'

const SRC = resolve(process.cwd(), 'src')
const STYLESHEETS = ['assets/main.css', 'core/styles/ui-next/skin.css']

const ZONED_PER_DAY = TRAFFIC_GROUPS.filter((group) => !group.spansZones).reduce(
  (sum, group) => sum + group.span,
  0,
)

/** Every `An + B` / `An` stride used by selectors matching `prefix`. */
function strides(css, prefix) {
  const pattern = new RegExp(`${prefix}:nth-child\\((\\d+)n\\b`, 'g')
  return [...css.matchAll(pattern)].map((match) => Number(match[1]))
}

describe.each(STYLESHEETS)('matrix dividers in %s', (path) => {
  const css = readFileSync(resolve(SRC, path), 'utf8')

  it('steps the zones row by the zoned columns of a day', () => {
    const found = strides(css, String.raw`\.app-datatable--matrix thead tr:nth-child\(3\) th`)

    expect(found.length).toBeGreaterThan(0)
    expect(new Set(found)).toEqual(new Set([ZONED_PER_DAY]))
  })

  it('steps the body rows by the leaf columns of a day', () => {
    const found = strides(css, String.raw`\.app-datatable--matrix tbody td`)

    expect(found.length).toBeGreaterThan(0)
    expect(new Set(found)).toEqual(new Set([COLUMNS_PER_DAY]))
  })
})
