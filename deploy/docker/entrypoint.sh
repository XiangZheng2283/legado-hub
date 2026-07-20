#!/bin/sh
set -eu

seed=/opt/legadohub/plugins/thirdparty
target=/app/plugins/sources/thirdparty

mkdir -p "$target"
if [ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    cp -a "$seed"/. "$target"/
fi

exec "$@"
