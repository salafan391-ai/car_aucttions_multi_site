#!/usr/bin/env bash
# Daily Encar import — runs at a scheduled time inside Railway (or locally)
# Railway cron: set startCommand to "bash run_daily_import.sh"
# Local cron:   0 3 * * * cd /Users/ahmedalwahaishi/tenant-cars && bash run_daily_import.sh >> /tmp/encar_import.log 2>&1

set -e

TODAY=$(date -u +%Y-%m-%d)
echo "==> Starting daily import for $TODAY at $(date -u)"

python manage.py import_encar_fast \
    --date "$TODAY" \
    --progress \
    --progress-every 2000

echo "==> Done at $(date -u)"
