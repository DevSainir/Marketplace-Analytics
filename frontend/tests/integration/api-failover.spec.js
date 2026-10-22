/**
 * What the SPA meets when NEITHER api instance can be reached.
 *
 * The two-instance pool survives a deploy, where the instances rotate one at a
 * time. It cannot survive a host reboot: `api` and `api_standby` share one
 * startup gate in docker-compose.yml, so they become ready together and the
 * failover has nowhere to land. Observed on 2026-09-07 — a kernel-upgrade
 * reboot left ~48 s in which every /api/ call got nginx's stock 502 HTML page,
 * which reaches extractErrorMessage() as an unparseable body.
 *
 * Why a test and not just the config comment: this whole path is invisible to
 * every other tier. The e2e stack has a healthy backend, so nothing exercises
 * a both-down request, and the failure mode of the load-bearing directive here
 * is SILENT — nginx follows only one error_page redirect without
 * `recursive_error_pages`, so dropping that one line reverts the response to a
 * raw 502 with no syntax error, no warning and no other test noticing.
 * Verified against nginx 1.27.5 on 2026-09-07: with the line, 503 and
 * application/json; without it, 502 and text/html.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const CONFS = {
  production: resolve(process.cwd(), 'docker/nginx.conf'),
  ci: resolve(process.cwd(), 'docker/nginx.ci.conf'),
}

const read = (which) => readFileSync(CONFS[which], 'utf8')

/** The body of a named location, e.g. `@api_down`. */
function namedLocation(conf, name) {
  const start = conf.indexOf(`location ${name} {`)
  if (start === -1) throw new Error(`No "location ${name}" block`)
  return conf.slice(start, conf.indexOf('\n    }', start))
}

describe.each(Object.keys(CONFS))('%s nginx: both api instances unreachable', (which) => {
  it('follows the second error_page hop', () => {
    // THE line this file exists for. nginx's default is one redirect, and
    // /api/ needs two: matched location -> @api_twin -> @api_down. Without it
    // the last hop is skipped in silence and the user gets the 502 back.
    expect(read(which)).toMatch(/^\s*recursive_error_pages\s+on;/m)
  })

  it('hands a twin that cannot be reached on to @api_down', () => {
    expect(namedLocation(read(which), '@api_twin')).toMatch(
      /error_page\s+502\s+503\s*=\s*@api_down;/,
    )
  })

  it('answers 503, not 502', () => {
    // 502 says "the upstream sent garbage" — a server fault worth paging for.
    // 503 says "come back shortly", which is what is true while a container
    // boots, and is what the auth store already retries rather than treating
    // as a dead session.
    expect(namedLocation(read(which), '@api_down')).toMatch(/return\s+503\s/)
  })

  it('says when to come back', () => {
    expect(namedLocation(read(which), '@api_down')).toMatch(
      /add_header\s+Retry-After\s+\d+\s+always;/,
    )
  })

  it('answers in the error envelope the SPA parses, not HTML', () => {
    // extractErrorMessage() reads `{error: {code, message}}` and falls through
    // to a generic string for anything else, so the shape here is what decides
    // whether the user reads a sentence about a restart or "Unexpected
    // error". The Content-Type has to agree, or Axios hands over a string.
    const block = namedLocation(read(which), '@api_down')

    expect(block).toContain('default_type application/json;')

    const body = block.match(/return\s+503\s+'([^']+)'/)?.[1]
    expect(body, 'no quoted body on the return').toBeTruthy()
    expect(JSON.parse(body).error.code).toBe('service_starting')
  })

  it('is not cached', () => {
    // A cached 503 would outlive the restart it describes.
    expect(namedLocation(read(which), '@api_down')).toMatch(
      /add_header\s+Cache-Control\s+"no-store"\s+always;/,
    )
  })

  it('keeps the shared security headers', () => {
    // nginx drops inherited add_header in any location that declares its own,
    // and this location declares two. The include is what puts them back.
    expect(namedLocation(read(which), '@api_down')).toMatch(
      /include\s+\/etc\/nginx\/snippets\/(tls|security)-headers\.conf;/,
    )
  })
})
