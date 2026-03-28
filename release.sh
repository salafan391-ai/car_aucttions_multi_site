#!/usr/bin/env bash
# Release command for Heroku (runtime) and Railway (startCommand, runtime).
# During Railway's Docker BUILD phase the internal DB hostname cannot be resolved.
# We detect this with a DNS lookup and skip migrations if DB is unreachable.
set -e

echo "==> collectstatic"
python manage.py collectstatic --noinput

# Extract DB host from DATABASE_URL for connectivity check
DB_HOST=$(python -c "
import os, urllib.parse
url = os.environ.get('DATABASE_URL', '')
if url:
    h = urllib.parse.urlparse(url).hostname or ''
    print(h)
")

if [ -z "$DB_HOST" ]; then
    echo "==> No DATABASE_URL set — skipping migrations."
    exit 0
fi

# Try to resolve the DB hostname — fails silently during Docker build
if ! getent hosts "$DB_HOST" > /dev/null 2>&1; then
    echo "==> Cannot resolve DB host '$DB_HOST' (build phase) — skipping migrations."
    exit 0
fi

MAX=5
WAIT=5

for i in $(seq 1 $MAX); do
    echo "==> migrate_schemas attempt $i/$MAX"
    PGCONNECT_TIMEOUT=30 python manage.py migrate_schemas --noinput && break
    echo "    failed — waiting ${WAIT}s before retry..."
    sleep $WAIT
    WAIT=$((WAIT * 2))
    if [ $i -eq $MAX ]; then
        echo "==> All $MAX attempts failed — aborting release."
        exit 1
    fi
done

echo "==> setup_public_tenant"
python manage.py setup_public_tenant
