/**
 * Architecture tests: the rules in the `frontend-architecture` skill
 * (`.claude/skills/frontend-architecture/SKILL.md`).
 *
 * ESLint already enforces the import boundaries — horizontal imports, downward
 * imports from `core/`, and parent-relative paths are all fatal there. What it
 * cannot express is the component-size rule and the public-API rule, which were
 * enforced by review alone until now. `MetricsTable.vue` had reached 1327 lines
 * against a 250-line limit before anyone noticed.
 *
 * Lives in `tests/` rather than beside a component because it is about the tree,
 * not about any one unit.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

// `process.cwd()` rather than `import.meta.url`: the specs run under jsdom,
// where `import.meta.url` is not a file: URL. Vitest always runs from the
// frontend package root.
const SRC = resolve(process.cwd(), 'src')
const MODULES = join(SRC, 'modules')

/** §3: a component past this many lines must be split into smaller ones. */
const MAX_COMPONENT_LINES = 250

/** Walk a directory tree, returning every file matching the predicate. */
function walk(dir, keep, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path, keep, found)
    else if (keep(path)) found.push(path)
  }
  return found
}

const lineCount = (path) => readFileSync(path, 'utf8').split('\n').length

describe('frontend architecture rules', () => {
  it('keeps every component under the size limit', () => {
    const oversized = walk(SRC, (p) => p.endsWith('.vue'))
      .map((path) => ({ path: path.slice(SRC.length + 1), lines: lineCount(path) }))
      .filter(({ lines }) => lines > MAX_COMPONENT_LINES)
      .sort((a, b) => b.lines - a.lines)

    expect(
      oversized,
      `Components over ${MAX_COMPONENT_LINES} lines — abstract UI elements into ` +
        `smaller components, and move a long <style> block into styles/<Name>.css ` +
        `(referenced as <style scoped src="...">):\n` +
        oversized.map((o) => `  ${o.path}: ${o.lines}`).join('\n'),
    ).toEqual([])
  })

  it('gives every module a public API', () => {
    const missing = readdirSync(MODULES, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .filter((name) => {
        try {
          statSync(join(MODULES, name, 'index.js'))
          return false
        } catch {
          return true
        }
      })

    expect(missing, 'Modules without an index.js facade').toEqual([])
  })

  it('exposes only the facade to other modules', () => {
    // The same rule ESLint enforces, asserted from the other direction: this
    // catches a file that silences the lint rule rather than obeying it.
    const offenders = []
    for (const path of walk(MODULES, (p) => p.endsWith('.js') || p.endsWith('.vue'))) {
      const relative = path.slice(MODULES.length + 1)
      const owner = relative.split('/')[0]
      const source = readFileSync(path, 'utf8')
      for (const [, target] of source.matchAll(/from '@\/modules\/([^']+)'/g)) {
        const [other, ...rest] = target.split('/')
        if (other === owner || rest.length === 0) continue
        offenders.push(`${relative} -> @/modules/${target}`)
      }
    }

    expect(
      offenders,
      'Horizontal imports must go through the target module\'s "@/modules/<name>" facade',
    ).toEqual([])
  })
})
