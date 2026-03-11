#!/usr/bin/env bash
# This script is used by Railway cron service.
# Set the Railway cron service startCommand to: bash cron_import.sh
# Set Railway cron schedule to: 30 2 * * *   (daily at 2:30am UTC = 5:30am Riyadh time)

set -e

TODAY=$(date -u +%Y-%m-%d)
echo "==> [$(date -u)] Starting daily Encar import for $TODAY"

python manage.py import_encar_fast \
    --date "$TODAY" \
    --progress \
    --progress-every 2000

echo "==> [$(date -u)] Import complete for $TODAY"
