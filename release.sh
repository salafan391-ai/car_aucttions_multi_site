#!/usr/bin/env bash
# Heroku release command — retries migrate_schemas up to 5 times with backoff.
# The release dyno network route to RDS is sometimes not ready for a few seconds.
# Uses a longer connect_timeout than web dynos (which are already running).
set -e

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
