#!/usr/bin/env bash
# Put production back on the build that was serving before the last deploy.
#
# Run from the deployment's checkout:
#
#   bash backend/scripts/deploy/rollback.sh < /dev/null
#
# A deploy is expected to leave two things behind for this:
#
#   * marketplace-service-{api,worker}:previous — the images the RUNNING
#     containers were created from, tagged before the new build. Taken off the
#     containers rather than off `:latest`, so a deploy that follows an
#     auto-rollback does not record the bad build as "previous".
#   * .frontend-releases/previous — the SPA release `current` pointed at before
#     the flip.
#
# Nothing runs this automatically. It rolled back on a failed smoke probe for one
# day (2026-09-29); that was removed — whether to roll back is a person's call.
#
# What it does NOT do is touch the database. The schema stays at the newer
# migration, which is fine for the kind of migration this repo writes (added
# columns, added tables — old code simply does not select them) and is NOT fine
# for a dropped or renamed column. Look at the migration before relying on a
# rollback across one; `alembic downgrade` is a separate, deliberate act.
#
# Every `compose up` below carries --no-deps, and that is load-bearing: without
# it compose starts `migrate` first, the OLD image runs `alembic upgrade head`
# against a database stamped with a revision it has never heard of, fails, and
# api/worker — which depend on it completing — never start.
#
# The git checkout is left where the deploy put it, so the next deploy's
# `git pull --ff-only` still works; the rollback lives in the images alone.
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/srv/marketplace_service}"
cd "$DEPLOY_PATH"

COMPOSE="docker compose --project-directory backend -f backend/docker/docker-compose.yml"
RELEASES="$DEPLOY_PATH/.frontend-releases"

# Check everything BEFORE changing anything: a rollback that stops half-way
# leaves the api on one build and the SPA on another.
for image in marketplace-service-api marketplace-service-worker; do
  if ! docker image inspect "${image}:previous" > /dev/null 2>&1; then
    echo "rollback: no ${image}:previous image — nothing to roll back to." >&2
    exit 1
  fi
done
previous_release=$(readlink "$RELEASES/previous" 2> /dev/null || true)
if [ -n "$previous_release" ] && [ ! -d "$RELEASES/$previous_release" ]; then
  echo "rollback: the previous SPA release ${previous_release} is gone." >&2
  exit 1
fi

for image in marketplace-service-api marketplace-service-worker; do
  docker tag "${image}:previous" "${image}:latest"
done

# Both nginx, because the edge sends users to either: one left on the release
# being rolled back serves it to whoever lands there. `|| true` because a reload
# that fails leaves the previous config running, which is not worth stopping a
# rollback over.
reload_nginx() {
  for nginx in frontend frontend_standby; do
    $COMPOSE exec -T "$nginx" nginx -s reload < /dev/null || true
  done
}

# The same one-at-a-time rotation the deploy uses, for the same reason: /api/
# is always served by the other instance.
for instance in api api_standby; do
  echo "rollback: rotating ${instance}…"
  $COMPOSE up -d --no-deps --force-recreate "$instance" < /dev/null
  state=""
  for _ in $(seq 1 30); do
    state=$($COMPOSE ps --format '{{.Name}} {{.Health}}' < /dev/null \
      | awk -v s="$instance" '$1 ~ s {print $2}' | head -1)
    [ "$state" = "healthy" ] && break
    sleep "${ROLLBACK_HEALTH_DELAY:-2}"
  done
  if [ "$state" != "healthy" ]; then
    echo "rollback: ${instance} did not become healthy on the previous image." >&2
    exit 1
  fi
  reload_nginx
done

# One rename(2), as in the deploy: there is no instant without a `current`.
if [ -n "$previous_release" ]; then
  ln -sfn "$previous_release" "$RELEASES/.current.rollback"
  python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' \
    "$RELEASES/.current.rollback" "$RELEASES/current"
  reload_nginx
  echo "rollback: SPA back on ${previous_release#releases/}"
else
  echo "rollback: no previous SPA release recorded; the SPA was left as it is."
fi

$COMPOSE up -d --no-deps --force-recreate worker beat < /dev/null

echo "rollback: done — api, api_standby, worker and beat run the previous build."
