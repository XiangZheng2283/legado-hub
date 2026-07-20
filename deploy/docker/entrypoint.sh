#!/bin/sh
set -eu

seed=/opt/legadohub/plugins/thirdparty
target=/app/plugins/sources/thirdparty
runtime_directories="/app/backend/data /app/backend/config /app/backend/generated /app/backend/runtime"

if [ "${1:-}" = "--initialize-runtime" ]; then
    if [ "$(id -u)" -ne 0 ]; then
        echo "LegadoHub runtime initialization must run as root." >&2
        exit 1
    fi
    runtime_uid="$(id -u legadohub)"
    runtime_gid="$(id -g legadohub)"
    shift
    for directory in $runtime_directories "$@"; do
        if ! mkdir -p "$directory"; then
            echo "LegadoHub runtime directory could not be created: $directory" >&2
            exit 1
        fi
        if ! chown "$runtime_uid:$runtime_gid" "$directory" 2>/dev/null; then
            echo "LegadoHub could not adjust directory ownership: $directory" >&2
            exit 1
        fi
    done
    exit 0
fi

for directory in $runtime_directories; do
    if ! mkdir -p "$directory" 2>/dev/null || [ ! -w "$directory" ]; then
        echo "LegadoHub runtime directory is not writable: $directory (container uid: $(id -u))" >&2
        exit 1
    fi
done

mkdir -p "$target"
if [ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    cp -a "$seed"/. "$target"/
fi

exec "$@"
