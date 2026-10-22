/**
 * One word for one thing, in every string a user can read.
 *
 * The thing a seller switches between — one WB seller account with its own
 * catalogue, its own P&L and its own tokens — is a **workspace**, plural
 * workspaces, and the code calls it the same. The word that keeps trying to
 * come back is "cabinet": the calque of what the Russian-language marketplace
 * calls a seller's account. It means nothing to an English reader, and WB's
 * own site is "the WB seller portal" when the UI needs to name it.
 *
 * **Why a test rather than a note.** A naming rule written down is a rule that
 * holds until the next person writes the obvious calque. This is the only
 * mechanism that makes the wrong word fail before it reaches a screen. The
 * same rule is enforced on the backend's exception messages by
 * `tests/unit/core/test_client_messages_use_seller_vocabulary.py`, which is
 * where the strings the API hands to a client live.
 *
 * **What it does NOT touch.** Identifiers: the word is matched whole, so a
 * variable such as `cabinetSpend` is left to the code's own naming.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve(process.cwd(), '..')
const TREES = [join(ROOT, 'frontend', 'src'), join(ROOT, 'tests', 'end-to-end')]

/** Files whose text can reach a screen. */
const LOOKS_LIKE_UI = (path) => /\.(vue|js)$/.test(path)

/** The banned word, singular or plural, in any case. */
const BANNED = /\bcabinets?\b/i

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
  it('calls a workspace a workspace, everywhere a user can read it', () => {
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
      'The word for a seller account is "workspace" (and WB\'s own site is the ' +
        '"WB seller portal"), never "cabinet":\n' +
        offenders.join('\n'),
    ).toEqual([])
  })

  it('actually reads the trees it claims to', () => {
    // Guard the guard: a broken path would make the rule above pass vacuously.
    const scanned = TREES.flatMap((tree) => walk(tree, LOOKS_LIKE_UI))

    expect(scanned.length).toBeGreaterThan(50)
  })
})
