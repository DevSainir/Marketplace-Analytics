/**
 * Nothing in `public/` may shadow an SPA route.
 *
 * nginx serves the app with `try_files $uri $uri/ /index.html`, and the second
 * branch — the one that looks for a DIRECTORY — fires before the fallback to
 * `index.html`. A directory in `public/` named like a route therefore captures
 * it: nginx finds the directory, listing is off, and a 403 arrives instead of
 * the page.
 *
 * This has already happened. A data pack once sat in a `public/` directory
 * named after a route, and that route answered 403 while its sibling routes
 * opened. No test saw it, and none could: Vite's dev server does not know this
 * rule, and any unknown path goes to `index.html` there anyway. It breaks only
 * behind nginx — like the CSP (see csp.spec.js).
 *
 * Hence the rule: a directory name in `public/` may not match the first segment
 * of a route. A file beside it is safe — `try_files` serves it as a file.
 */
import { readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import router from '@/core/router'

const PUBLIC = resolve(process.cwd(), 'public')

/** Directories in `public/` — only they capture `$uri/`. */
function publicDirectories(dir = PUBLIC, prefix = '') {
  const found = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (!statSync(path).isDirectory()) continue
    const asUrl = prefix + '/' + entry
    found.push(asUrl)
    found.push(...publicDirectories(path, asUrl))
  }
  return found
}

/** Paths of every app route — already expanded, nested ones included. */
function routePaths() {
  return router.getRoutes().map((route) => route.path)
}

describe('static files in public/', () => {
  it('never take a route path', () => {
    const directories = new Set(publicDirectories())
    const clashes = routePaths().filter((path) => directories.has(path))

    expect(
      clashes,
      'A directory in public/ named like a route captures it in nginx ' +
        '(`try_files $uri $uri/`) and the page answers 403. Rename the directory ' +
        'or keep the file out of a same-named directory:\n' +
        clashes.map((c) => `  public${c}/ shadows the route ${c}`).join('\n'),
    ).toEqual([])
  })
})
