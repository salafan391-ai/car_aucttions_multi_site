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

# Populate Arabic names and logos for any new manufacturers created during import
echo "==> Setting manufacturer Arabic names..."
python manage.py set_manufacturer_arabic

echo "==> Setting manufacturer logos..."
python manage.py set_manufacturer_logos

# Clear stale cache so all tenants see fresh data immediately
if [ -n "$REDIS_URL" ]; then
    echo "==> Clearing cache..."
    python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"
fi
