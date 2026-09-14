/**
 * One word for one thing, in every string a user can read.
 *
 * The thing a seller switches between — one WB seller account with its own
 * catalogue, its own P&L and its own tokens — is a **кабинет**. Full form
 * «Личный кабинет», short form «Кабинет», plural «Кабинеты». It was called
 * «рабочее пространство» in eleven places and «кабинет» in none, which is a
 * word nobody outside this repo uses for it and which does not match what the
 * marketplace itself calls a seller's account.
 *
 * **Why a test rather than a note.** A naming rule written down is a rule that
 * holds until the next person writes the obvious English calque. This is the
 * only mechanism that makes the wrong word fail before it reaches a screen.
 * The same rule is enforced on the backend's exception messages by
 * `tests/unit/core/test_messages_are_russian.py`, which is where the strings
 * the API hands to a client live.
 *
 * **What it does NOT touch.** The code says `workspace` everywhere — the model,
 * the table, the store, the header, the route — and that is deliberate: the
 * identifier is not the noun a user reads, renaming it would be a migration
 * across four modules, and English identifiers behind a Russian UI are how the
 * whole codebase already works. This test is about the words on the screen.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve(process.cwd(), '..')
const TREES = [join(ROOT, 'frontend', 'src'), join(ROOT, 'tests', 'end-to-end')]

/** Files whose text can reach a screen. */
const LOOKS_LIKE_UI = (path) => /\.(vue|js)$/.test(path)

/**
 * The banned stem, matching every case ending — пространство, пространства,
 * пространств, пространствами. One stem catches them all.
 */
const BANNED = /пространств/i

/** Walk a directory tree, returning every file matching the predicate. */
function walk(dir, keep, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path, keep, found)
    else if (keep(path)) found.push(path)
  }
  return found
}

describe('naming', () => {
  it('calls a кабинет a кабинет, everywhere a user can read it', () => {
    const offenders = []
    for (const tree of TREES) {
      for (const path of walk(tree, LOOKS_LIKE_UI)) {
        readFileSync(path, 'utf8')
          .split('\n')
          .forEach((line, index) => {
            if (BANNED.test(line)) {
              offenders.push(`${path.slice(ROOT.length + 1)}:${index + 1}: ${line.trim()}`)
            }
          })
      }
    }

    expect(
      offenders,
      'The word for a seller account is «кабинет» («Личный кабинет» in full), ' +
        'never «рабочее пространство»:\n' +
        offenders.join('\n'),
    ).toEqual([])
  })

  it('actually reads the trees it claims to', () => {
    // Guard the guard: a broken path would make the rule above pass vacuously.
    const scanned = TREES.flatMap((tree) => walk(tree, LOOKS_LIKE_UI))

    expect(scanned.length).toBeGreaterThan(50)
  })
})
