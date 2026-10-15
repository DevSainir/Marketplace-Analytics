#!/bin/sh
# The worker's HEALTHCHECK — and, after enough failures in a row, its restart.
#
# Docker never restarts an `unhealthy` container: `restart: unless-stopped`
# acts on an EXIT, and a worker whose every task dies still has a live PID 1.
# On 2026-10-15 the worker failed this ping 500 times in a row (SIGBUS from a
# full metrics tmpfs) and ran nothing from 04:01 to 07:03 MSK, including the
# 05:05 nightly harvest, until somebody restarted it by hand. A restart alone
# would have fixed it: it remounts both tmpfs volumes empty.
#
# So this script counts consecutive failures and, at RESTART_AFTER, sends PID 1
# SIGTERM: Celery's WARM shutdown, which stops taking messages and lets running
# tasks finish within `stop_grace_period`. PID 1 exits, and the restart policy
# brings up a fresh container. Twice that many failures and it sends SIGQUIT,
# the cold shutdown, for a worker too wedged to finish warmly. (SIGKILL is not
# an option: the kernel ignores it for a namespace's PID 1 sent from inside.)
#
# RESTART_AFTER=6 at a 30 s interval is three minutes — past the ~45 s a fresh
# worker needs to answer its first ping, and past a Redis restart. What it
# costs is that a Redis outage longer than that restarts the worker too, which
# is harmless: its tasks are acked late and come back.
#
# The count lives on its own small tmpfs (`/tmp/healthcheck` in compose), so it
# is empty on every container start by construction. In the container's
# ordinary /tmp it would survive the restart it caused, and the first
# not-yet-ready ping of the new worker would fire the next one.
#
# `PROMETHEUS_MULTIPROC_DIR=` keeps the ping out of the metrics tmpfs
# altogether: empty is normalised to absent, so it counts in memory. The exit
# sweep in `metrics/lifecycle.py` would clean up after it too, but not after a
# ping SIGKILLed by the healthcheck timeout, which runs no exit hook.
#
# Every knob is an environment variable only so the unit test can run this
# exact script against a stand-in process; the container sets none of them.

state_dir="${HEALTHCHECK_STATE_DIR:-/tmp/healthcheck}"
target="${HEALTHCHECK_TARGET_PID:-1}"
restart_after="${HEALTHCHECK_RESTART_AFTER:-6}"
state="$state_dir/consecutive-failures"

if PROMETHEUS_MULTIPROC_DIR= celery -A src.core.celery_app.celery_app inspect ping; then
    rm -f "$state"
    exit 0
fi

mkdir -p "$state_dir" 2>/dev/null
failures=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 ))
echo "$failures" > "$state" 2>/dev/null

if [ "$failures" -ge $(( restart_after * 2 )) ]; then
    echo "worker failed $failures health checks in a row; cold shutdown (SIGQUIT) for a restart"
    kill -QUIT "$target"
elif [ "$failures" -ge "$restart_after" ]; then
    echo "worker failed $failures health checks in a row; warm shutdown (SIGTERM) for a restart"
    kill -TERM "$target"
fi
exit 1
