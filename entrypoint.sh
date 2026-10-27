#!/bin/sh
# Konteyner ishga tushganda: migratsiya -> statik fayllar -> server.
set -eu

if [ "${DJANGO_RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] migrate"
    python manage.py migrate --noinput
fi

echo "[entrypoint] collectstatic"
python manage.py collectstatic --noinput

echo "[entrypoint] start: $*"
exec "$@"
