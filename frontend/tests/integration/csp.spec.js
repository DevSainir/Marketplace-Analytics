/**
 * The production CSP must permit what the SPA actually does.
 *
 * This header is the one piece of the app's behaviour that NO other tier can
 * see. The Vite dev server sends no CSP at all, so a directive that blocks a
 * real feature looks perfectly healthy in development and on every unit,
 * component and integration run — it only bites once nginx serves the app, in
 * CI and in production.
 *
 * That is not hypothetical: `img-src 'self' data:` silently blocked every A/B
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

  it('lets the SKU thumbnails load from WB’s own image CDN', () => {
    // The monitoring SKU search, «Сравнение SKU» and the per-SKU P&L show the
    // seller's card photos. Those are public, unauthenticated links on
    // `basket-NN.wbbasket.ru`, so `<img>` loads them directly rather than
    // through the API the way the A/B variants are — proxying hundreds of
    // table rows would buy nothing, since the images are public either way.
    // Without this source they are blank in production only (see the header).
    expect(directives()['img-src']).toContain('https://*.wbbasket.ru')
  })

  it('names WB’s image CDN and nothing else, anywhere in the policy', () => {
    // The strongest CSP is the one that names nobody but us, and this one was
    // that until the SKU thumbnails landed. Until the Inter Tight typeface was
    // self-hosted it carried two Google origins — every one of
    // them a host that can serve content to our users, and a host whose logs
    // learn every visitor's IP.
    //
    // WB is the deliberate exception and this is the whole of it: the seller's
    // own marketplace, serving the seller's own product photos, as images
    // only. The assertion is an exact list rather than a "no new hosts" rule
    // so that widening it to a second origin — or letting WB into `script-src`
    // or `connect-src` — is a decision somebody has to write down here.
    const offenders = Object.entries(directives()).flatMap(([name, sources]) =>
      sources.filter((source) => source.includes('//')).map((source) => `${name} ${source}`),
    )

    expect(offenders).toEqual(['img-src https://*.wbbasket.ru'])
  })

  it('serves the typeface from our own origin', () => {
    // Self-hosted, so `font-src` needs no host: `data:` stays for any inline
    // face a dependency injects.
    const sources = directives()['font-src']

    expect(sources).toContain("'self'")
    expect(sources.some((source) => source.includes('fonts.gstatic'))).toBe(false)
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
