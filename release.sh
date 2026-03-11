#!/usr/bin/env bash
# Release command for Heroku (and Railway via startCommand).
# During Railway's Docker BUILD phase DATABASE_URL is not available —
# we detect this and skip migrations entirely so the build succeeds.
set -e

if [ -z "$DATABASE_URL" ]; then
    echo "==> No DATABASE_URL found (build phase) — skipping migrations."
    echo "==> collectstatic only"
    python manage.py collectstatic --noinput
    exit 0
fi

echo "==> collectstatic"
python manage.py collectstatic --noinput

MAX=5
WAIT=5

for i in $(seq 1 $MAX); do
    echo "==> migrate_schemas attempt $i/$MAX"
    PGCONNECT_TIMEOUT=30 python manage.py migrate_schemas --noinput && exit 0
    echo "    failed — waiting ${WAIT}s before retry..."
    sleep $WAIT
    WAIT=$((WAIT * 2))
done

echo "==> All $MAX attempts failed — aborting release."
exit 1
