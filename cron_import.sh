#!/usr/bin/env bash
# This script is used by Railway cron service.
# Set the Railway cron service startCommand to: bash cron_import.sh
# Set Railway cron schedule to: 0 4 * * *   (daily at 4:00am UTC = 7:00am Riyadh time)

set -e

echo "==> [$(date -u)] Starting daily Encar import"

python manage.py run_encar_import

echo "==> [$(date -u)] Import complete"

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
