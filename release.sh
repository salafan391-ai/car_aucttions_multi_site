#!/usr/bin/env bash
# Heroku release command — retries migrate_schemas up to 5 times with backoff.
# Handles transient "timeout expired" errors on release dyno startup.
set -e

MAX=5
WAIT=5

for i in $(seq 1 $MAX); do
    echo "==> migrate_schemas attempt $i/$MAX"
    python manage.py migrate_schemas --noinput && exit 0
    echo "    failed — waiting ${WAIT}s before retry..."
    sleep $WAIT
    WAIT=$((WAIT * 2))   # exponential backoff: 5s, 10s, 20s, 40s
done

echo "==> All $MAX attempts failed — aborting release."
exit 1
