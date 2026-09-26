/**
 * The design system has one palette, and these tests are what keep it one.
 *
 * Until 2026-09-26 `tailwind.config.js` still held the PREVIOUS palette — teal
 * action, grey canvas — while `ui-next` re-pointed only the utility classes in
 * markup. Every `@apply` compiled against the config, so the table paginator,
 * the totals row and the record cards shipped in the old colours beside pages
 * in the new ones, and nothing failed.
 *
 * Now every token resolves to a `ui-next` custom property and Tailwind's stock
 * palette is replaced outright. Two things can still bring a second palette
 * back, and neither fails a build: a literal hex in the config, and a stock
 * class in markup (`bg-slate-100`), which the compiler drops silently.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = process.cwd()
const SRC = resolve(ROOT, 'src')

/** Walk a directory tree, returning every file matching the predicate. */
function walk(dir, keep, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path, keep, found)
    else if (keep(path)) found.push(path)
  }
  return found
}

const STOCK_PALETTE =
  /\b(?:bg|text|border|ring|divide|outline|from|via|to|fill|stroke|decoration|placeholder|accent|caret|shadow)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/g

describe('design tokens', () => {
  it('defines no colour, shadow or radius value in the Tailwind config', () => {
    const config = readFileSync(join(ROOT, 'tailwind.config.js'), 'utf8')
      .split('\n')
      .filter((line) => !line.trim().startsWith('//'))
      .join('\n')
    // White, black and the one chart accent are the only literals allowed.
    const literals = [...config.matchAll(/#[0-9a-fA-F]{3,8}\b/g)]
      .map((m) => m[0].toLowerCase())
      .filter((hex) => !['#ffffff', '#000000', '#4f46e5'].includes(hex))

    expect(literals, 'a literal colour in tailwind.config.js is a second palette').toEqual([])
  })

  it('uses no stock Tailwind palette class anywhere in the source', () => {
    const offenders = walk(
      SRC,
      (p) => /\.(vue|js|css)$/.test(p) && !p.endsWith('.spec.js'),
    ).flatMap((path) =>
      [...readFileSync(path, 'utf8').matchAll(STOCK_PALETTE)].map(
        (m) => `${path.slice(SRC.length + 1)}: ${m[0]}`,
      ),
    )

    expect(
      offenders,
      'Stock palette classes do not exist in this app and render as nothing — ' +
        'use a design-system token (text-muted, bg-status-positive/10, …):\n' +
        offenders.join('\n'),
    ).toEqual([])
  })
})
