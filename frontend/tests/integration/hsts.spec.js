/**
 * HSTS is what makes "HTTPS only" survive the second visit.
 *
 * Like the CSP next door, this header is invisible to every other tier: the
 * Vite dev server never sends it, so weakening it looks perfectly healthy
 * everywhere except on the deployment where it matters. Unlike the CSP, a
 * weakened HSTS breaks nothing and shows no console warning — it just quietly
 * shortens how long a browser refuses to speak plain HTTP to us, which is a
 * property nobody would notice was gone.
 *
 * The header was once confirmed by observation: it was seen on the wire on
 * 2026-08-29. That was true of that day. This is what keeps it true.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const TLS_HEADERS = resolve(process.cwd(), 'docker/snippets/tls-headers.conf')

/** The `Strict-Transport-Security` value as nginx would send it. */
function hsts() {
  const conf = readFileSync(TLS_HEADERS, 'utf8')
  const match = conf.match(/add_header\s+Strict-Transport-Security\s+"([^"]+)"/)
  if (!match) throw new Error('No Strict-Transport-Security in tls-headers.conf')
  return match[1]
}

describe('production HSTS', () => {
  it('promises at least a year', () => {
    // Under a year a browser that visits rarely falls back to plain HTTP
    // between visits, which is the window the header exists to close. The
    // deployed value is two years; this asserts the floor, not the number, so
    // raising it is not a test change.
    const maxAge = Number(hsts().match(/max-age=(\d+)/)?.[1])

    expect(maxAge).toBeGreaterThanOrEqual(31536000)
  })

  it('covers subdomains', () => {
    // Without this the promise applies to the apex alone, and a future
    // subdomain served over plain HTTP would be reachable from a link.
    expect(hsts()).toContain('includeSubDomains')
  })

  it('does not silently acquire preload', () => {
    // Deliberately absent, and this asserts the decision rather than the
    // absence: `preload` hands the same promise to browser vendors' built-in
    // lists, where undoing it takes months instead of a max-age. Adding it
    // should be a conversation, not a one-word edit that no test notices.
    expect(hsts()).not.toContain('preload')
  })

  it('is not sent from the plain-HTTP server', () => {
    // HSTS over plain HTTP is meaningless and the CI overlay has no
    // certificate, which is why this lives in tls-headers.conf rather than in
    // security-headers.conf that every server block includes.
    const shared = readFileSync(
      resolve(process.cwd(), 'docker/snippets/security-headers.conf'),
      'utf8',
    )

    expect(shared).not.toContain('Strict-Transport-Security')
  })
})
