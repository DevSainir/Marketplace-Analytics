/**
 * The production CSP must permit what the SPA actually does.
 *
 * This header is the one piece of the app's behaviour that NO other tier can
 * see. The Vite dev server sends no CSP at all, so a directive that blocks a
 * real feature looks perfectly healthy in development and on every unit,
 * component and integration run — it only bites once nginx serves the app, in
 * CI and in production.
 *
 * That is not hypothetical: `img-src 'self' data:` silently blocked every A/Б
 * variant thumbnail (2026-08-21). The photos sit behind an authenticated
 * route, so the SPA fetches their bytes with the API client and hands `<img>`
 * an object URL — and `blob:` was not in the directive. The browser reported it
 * only as a console violation and a `naturalWidth` of 0; the element was still
 * "visible", so even the browser tier had to be looking for the right thing.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const HEADERS = resolve(process.cwd(), 'docker/snippets/security-headers.conf')

/** The `Content-Security-Policy` value, split into `name -> sources`. */
function directives() {
  const conf = readFileSync(HEADERS, 'utf8')
  const match = conf.match(/add_header\s+Content-Security-Policy\s+"([^"]+)"/)
  if (!match) throw new Error('No Content-Security-Policy in security-headers.conf')
  return Object.fromEntries(
    match[1]
      .split(';')
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...sources] = part.split(/\s+/)
        return [name, sources]
      }),
  )
}

describe('production Content-Security-Policy', () => {
  it('lets the SPA render images it fetched itself', () => {
    // Authenticated images cannot be loaded by `<img src>` directly — the
    // access token lives in memory — so they arrive as blobs and are rendered
    // through object URLs. Dropping `blob:` blanks them in production only.
    expect(directives()['img-src']).toContain('blob:')
  })

  it('still refuses images from anywhere off-origin', () => {
    // The point of the directive survives: `blob:` is same-origin content the
    // page itself created. A remote host here would be a real widening.
    const sources = directives()['img-src']

    expect(sources.some((source) => source.includes('//'))).toBe(false)
    expect(sources).toContain("'self'")
  })

  it('keeps the directives the app depends on', () => {
    // A CSP is edited rarely and by hand, so a typo in one directive can
    // disable a feature nobody tests until a user reports it.
    const csp = directives()

    expect(csp['default-src']).toEqual(["'self'"])
    expect(csp['connect-src']).toContain("'self'")
    expect(csp['frame-ancestors']).toEqual(["'none'"])
    expect(csp['object-src']).toEqual(["'none'"])
  })
})
