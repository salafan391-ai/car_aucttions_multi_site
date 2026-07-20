#!/usr/bin/env bash
# This script is used by Railway cron service.
# Set the Railway cron service startCommand to: bash cron_import.sh
# Set Railway cron schedule to: 0 4 * * *   (daily at 4:00am UTC = 7:00am Riyadh time)

set -e

echo "==> [$(date -u)] Starting daily Encar import"

python manage.py run_encar_import

echo "==> [$(date -u)] Import complete"

# Fill Arabic names on anything the import just created. Only touches rows whose
# name_ar is empty, so existing translations are never disturbed.
echo "==> Setting Arabic names for new makes/models..."
python manage.py set_car_arabic_names || echo "==> Arabic name fill failed (non-fatal)"

echo "==> Updating exchange rates..."
python manage.py update_exchange_rates || echo "==> Exchange rate update failed (non-fatal)"

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

# Clear stale cache so all tenants see fresh data immediately
if [ -n "$REDIS_URL" ]; then
    echo "==> Clearing cache..."
    python manage.py shell -c "from django.core.cache import cache; cache.clear(); print('Cache cleared.')"
fi

# Warm the Google Search Console cache for tenant dashboards (after the clear)
echo "==> Refreshing GSC metrics cache..."
python manage.py refresh_gsc || echo "==> GSC refresh failed (non-fatal)"
