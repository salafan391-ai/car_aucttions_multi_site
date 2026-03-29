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

# Fill in Arabic names / logos only for manufacturers that are still missing them
python manage.py shell -c "
from cars.models import Manufacturer
missing_ar = Manufacturer.objects.filter(name_ar__isnull=True).count()
missing_logo = Manufacturer.objects.filter(logo__isnull=True).count()
print(f'Manufacturers missing Arabic: {missing_ar}, missing logo: {missing_logo}')
" | tee /tmp/mfr_check.txt

if grep -q "missing Arabic: [^0]" /tmp/mfr_check.txt; then
    echo "==> Setting manufacturer Arabic names..."
    python manage.py set_manufacturer_arabic
fi

if grep -q "missing logo: [^0]" /tmp/mfr_check.txt; then
    echo "==> Setting manufacturer logos..."
    python manage.py set_manufacturer_logos
fi

# Remove lease cars imported today (cannot be resold/exported)
echo "==> [$(date -u)] Running lease car check..."
python manage.py check_lease_cars
echo "==> [$(date -u)] Lease check complete."

# Remove cars no longer listed on Encar (404)
echo "==> [$(date -u)] Running availability check..."
python manage.py check_encar_availability --workers 20 --batch-size 100 --timeout 7
echo "==> [$(date -u)] Availability check complete."

# Clear stale cache so all tenants see fresh data immediately
if [ -n "$REDIS_URL" ]; then
    echo "==> Clearing cache..."
    python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"
fi
