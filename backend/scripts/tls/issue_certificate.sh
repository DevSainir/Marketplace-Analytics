#!/usr/bin/env bash
# Issue (or re-issue) the TLS certificate covering every host this deployment
# serves, and move renewals onto a method that actually works.
#
# WHY THIS EXISTS RATHER THAN A COMMAND IN A README.
#
# The certificate issued on 2026-07-14 was configured with
# `authenticator = standalone`, which asks certbot to bind port 80 itself.
# nginx holds port 80. So every automatic renewal would have failed: the
# `certbot.timer` fires twice daily, found the certificate "not yet due", and
# would have started failing around 2026-09-12 with expiry on 2026-10-12.
# Nothing reports that until the site stops loading, and the failure arrives a
# month after the cause.
#
# Running this once switches the renewal to `webroot`, which works with nginx
# running and needs no downtime. certbot rewrites
# /etc/letsencrypt/renewal/example.com.conf from the flags given here, so
# the fix persists for every future automatic renewal.
#
# The webroot is a HOST directory bind-mounted into the frontend container
# read-only (docker-compose.yml). That mount is the part that makes webroot
# possible at all: certbot writes on the host, nginx reads in the container, and
# a webroot inside the image would be one certbot could never reach.
#
# Run on the host, as root:
#     bash backend/scripts/tls/issue_certificate.sh
set -euo pipefail

WEBROOT=/var/www/certbot
DOMAINS=(example.com www.example.com grafana.example.com)

command -v certbot >/dev/null || { echo "certbot is not installed." >&2; exit 1; }

# Must exist before nginx is asked to serve from it, and before certbot writes.
mkdir -p "$WEBROOT/.well-known/acme-challenge"
chmod 755 "$WEBROOT" "$WEBROOT/.well-known" "$WEBROOT/.well-known/acme-challenge"

# Every name must resolve FROM THE INTERNET, or the ACME server cannot reach the
# challenge and certbot fails partway — leaving the EXISTING certificate
# untouched but the renewal config half-rewritten. Checked first so the failure
# is a clear message rather than a confusing one.
#
# Asked of PUBLIC resolvers, and deliberately not of this box via `getent hosts`
# — that is the wrong vantage point, in both directions:
#
#   * False negative, observed on 2026-09-09 and the reason this is written out.
#     The record was live at the registrar and correct on every public resolver,
#     while this host's upstream still served NXDOMAIN with ~12 minutes left on
#     the zone's 3601 s negative TTL, cached because the name had been looked up
#     BEFORE it existed. Nothing local fixes that: `resolvectl flush-caches`
#     clears the stub's cache, not the provider resolver's. The box's two
#     upstreams even disagreed with each other, so the answer depended on which
#     one systemd-resolved happened to be using.
#   * False positive, the same coin: a name resolvable only from inside this
#     network would pass the check and then fail validation.
#
# Let's Encrypt resolves from the public internet, so that is what to ask. Any
# one resolver answering is enough — this is a pre-flight sanity check, not a
# propagation audit.
PUBLIC_RESOLVERS=(1.1.1.1 8.8.8.8 9.9.9.9)

command -v dig >/dev/null || { echo "dig is not installed (apt install dnsutils)." >&2; exit 1; }

for domain in "${DOMAINS[@]}"; do
  resolved=""
  for resolver in "${PUBLIC_RESOLVERS[@]}"; do
    if [ -n "$(dig +short +time=3 +tries=1 "@$resolver" "$domain" A 2>/dev/null)" ]; then
      resolved=$resolver
      break
    fi
  done
  if [ -z "$resolved" ]; then
    echo "DNS: $domain does not resolve on any public resolver. Add its A record first." >&2
    exit 1
  fi
  echo "DNS: $domain resolves (asked $resolved)."
done

args=()
for domain in "${DOMAINS[@]}"; do args+=(-d "$domain"); done

# `--expand` because this adds a name to a certificate that already exists;
# without it certbot asks interactively and a non-tty run stalls.
# `--cert-name` pins the lineage so the paths nginx already references
# (/etc/letsencrypt/live/example.com/) stay exactly the same — otherwise
# certbot would create a `-0001` directory and nginx would keep serving the old
# certificate while the new one sat unused.
certbot certonly \
  --webroot -w "$WEBROOT" \
  --cert-name example.com \
  --expand \
  --non-interactive \
  --agree-tos \
  --keep-until-expiring \
  "${args[@]}"

# Install the deploy hook, so EVERY FUTURE renewal reloads nginx too.
#
# Renewing the file is only half the job: nginx holds its certificate in memory
# from the moment it started and will keep serving the old one off a perfectly
# correct file. Doing this here rather than leaving it as a manual step is the
# point of the script — a fix that depends on somebody remembering it in sixty
# days is the same class of bug as the `standalone` authenticator above.
HOOK_DIR=/etc/letsencrypt/renewal-hooks/deploy
mkdir -p "$HOOK_DIR"
install -m 0755 "$(dirname "$0")/reload_nginx_hook.sh" "$HOOK_DIR/reload-nginx.sh"
echo "Deploy hook installed at $HOOK_DIR/reload-nginx.sh"

echo
echo "Names now on the certificate:"
openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -text \
  | grep -A1 "Subject Alternative Name" | tail -1 | sed 's/^/  /'
echo "Renewal method now:"
grep -E "^authenticator|^webroot_path" /etc/letsencrypt/renewal/example.com.conf | sed 's/^/  /'

# Reload now, through the very hook just installed — so this run both serves the
# new name immediately AND proves the hook works, rather than leaving its first
# real execution to an unattended renewal two months from now.
echo
echo "Reloading nginx via the deploy hook:"
"$HOOK_DIR/reload-nginx.sh"
