/**
 * Every name on the certificate must be a name nginx can answer for on port 80.
 *
 * HTTP-01 validation works by Let's Encrypt resolving each domain and fetching
 * /.well-known/acme-challenge/<token> over PLAIN HTTP. So renewal depends on a
 * relationship between two files that have no reason to be edited together:
 * the domain list in backend/scripts/tls/issue_certificate.sh, and the port-80
 * server in docker/nginx.conf. Drop a name from the server_name, or turn the
 * ACME location into a redirect, and nothing breaks today — the certificate is
 * already issued. It breaks at the next renewal, up to sixty days later, and
 * the symptom is the whole site becoming unreachable.
 *
 * This deployment has already been bitten by exactly that shape once: the
 * renewal was configured `authenticator = standalone` against an nginx holding
 * port 80, so every automatic renewal would have failed from ~2026-09-12 for a
 * certificate expiring 2026-10-12 — a month between cause and symptom, with
 * nothing reporting it in between.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const NGINX = readFileSync(resolve(process.cwd(), 'docker/nginx.conf'), 'utf8')
const ISSUE_SCRIPT = readFileSync(
  resolve(process.cwd(), '../backend/scripts/tls/issue_certificate.sh'),
  'utf8',
)

/**
 * The script with its comments removed.
 *
 * Assertions that something is ABSENT need this: the script explains at length
 * why it does not use `getent hosts` and does not pass `--standalone`, so a
 * naive search finds both phrases in the prose that exists to warn against
 * them, and the test passes or fails on the documentation rather than the code.
 */
function scriptCode() {
  return ISSUE_SCRIPT.split('\n')
    .filter((line) => !/^\s*#/.test(line))
    .join('\n')
}

/** The domains the certificate is issued for — the script is the source of truth. */
function certificateDomains() {
  const list = ISSUE_SCRIPT.match(/^DOMAINS=\(([^)]+)\)/m)?.[1]
  if (!list) throw new Error('No DOMAINS=( ... ) in issue_certificate.sh')
  return list.trim().split(/\s+/)
}

/** The `server { ... }` block that listens on plain HTTP — where ACME lands. */
function plainHttpServer() {
  const block = NGINX.split(/\nserver \{/)
    .slice(1)
    .find((b) => /listen\s+80\b/.test(b))
  if (!block) throw new Error('No server block listening on port 80')
  return block
}

describe('certificate domains and ACME reachability', () => {
  it('issues for more than the apex', () => {
    // Guards the parser as much as the config: a DOMAINS array that silently
    // stopped matching would make every assertion below vacuously true.
    expect(certificateDomains().length).toBeGreaterThan(1)
  })

  it.each(certificateDomains())('nginx answers for %s on port 80', (domain) => {
    expect(plainHttpServer()).toContain(domain)
  })

  it('serves the ACME challenge instead of redirecting it', () => {
    // The port-80 server exists to 301 everything to HTTPS. This one location
    // must be carved out of that, or validation follows a redirect it is not
    // obliged to follow and renewal fails.
    const server = plainHttpServer()
    const acme = server.slice(server.indexOf('location /.well-known/acme-challenge/'))

    expect(acme).toContain('root /var/www/certbot;')
    expect(acme.slice(0, acme.indexOf('}'))).not.toContain('return 301')
  })

  it('renews by webroot, never standalone', () => {
    // `standalone` asks certbot to bind port 80, which nginx holds. It is the
    // configuration this deployment actually shipped with, so it is named here
    // rather than merely implied.
    expect(scriptCode()).toMatch(/--webroot\s+-w\s+"?\$WEBROOT"?/)
    expect(scriptCode()).not.toContain('--standalone')
  })

  it('keeps the certificate lineage nginx already points at', () => {
    // Without --cert-name, adding a name makes certbot start a `-0001`
    // lineage; nginx keeps reading the old path and serves the old cert.
    expect(ISSUE_SCRIPT).toContain('--cert-name example.com')

    const certPath = NGINX.match(/ssl_certificate\s+(\S+);/)?.[1]
    expect(certPath).toContain('/live/example.com/')
  })

  it('checks resolution from the public internet, not from the box', () => {
    // `getent hosts` asks this host's own resolver, which is the wrong vantage
    // point: on 2026-09-09 it reported NXDOMAIN for a name that was live on
    // every public resolver, because the box's upstream had cached the negative
    // answer from a lookup made before the record existed. The inverse is worse
    // — a name resolvable only internally would pass and then fail validation.
    expect(scriptCode()).not.toMatch(/getent\s+hosts/)
    expect(scriptCode()).toContain('PUBLIC_RESOLVERS=')
  })

  it('installs the deploy hook that reloads nginx after a renewal', () => {
    // nginx reads its certificate once and serves it from memory. Renewing the
    // file without reloading leaves the old certificate on the wire while every
    // check of the file passes — so the hook is part of the fix, not a nicety.
    expect(ISSUE_SCRIPT).toContain('/etc/letsencrypt/renewal-hooks/deploy')
    expect(ISSUE_SCRIPT).toContain('reload_nginx_hook.sh')
  })

  it('gives grafana its own TLS server block', () => {
    // The whole point of the subdomain: a separate browser origin from the SPA.
    expect(NGINX).toMatch(/server_name\s+grafana\.example\.com;/)
  })
})
