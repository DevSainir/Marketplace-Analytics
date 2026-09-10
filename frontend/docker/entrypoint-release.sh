#!/bin/sh
# Point nginx at the release it should serve, before nginx starts.
#
# The served bundle and the config that serves it are NOT in this image — they
# arrive as a release directory, so that a new SPA build does not change this
# image and therefore does not force the container to be recreated. Recreating
# it is a hard stop for the whole site (there is only one nginx and it holds
# :443), which is the outage this whole arrangement exists to remove: the
# deploy installs a new release beside the old one, flips a symlink and sends
# `nginx -s reload`, and no connection is dropped.
#
# FRONTEND_ROOT names where that release is. The default is the host directory
# the production deploy writes to; the e2e stack overrides it to a path baked
# into its own image, so a throwaway stack needs no host state and the base
# file's bind mount is simply left unused (the same trick its overlay already
# plays with :443 and /etc/letsencrypt).
#
# Symlinked here rather than at build time so one image can serve either.
set -eu

root="${FRONTEND_ROOT:-/srv/frontend/current}"

if [ ! -d "$root/conf.d" ]; then
    echo "entrypoint-release: no release at $root — nothing to serve." >&2
    exit 1
fi

ln -sfn "$root/conf.d" /etc/nginx/conf.d
ln -sfn "$root/snippets" /etc/nginx/snippets
