#!/usr/bin/env bash
# check_availability.sh
# ---------------------------------------------------------------
# Option A: Railway Cron Service (separate service)
#   startCommand: bash check_availability.sh
#   Schedule (in Railway dashboard): 0 */4 * * *   (every 4 hours)
#
# Option B: run as a long-lived background worker (loops forever)
#   Set AVAILABILITY_LOOP=1 as a Railway env var, then set this
#   as the startCommand of a Worker service (no cron schedule needed).
#
# Scans ALL available cars (~60 min at 20 workers) against the Encar
# API and DELETES any that are no longer listed (404).
# Cache is busted automatically after each delete batch.
# ---------------------------------------------------------------

set -e

run_check() {
    echo "==> [$(date -u)] Starting Encar availability check (all cars)"
    python manage.py check_encar_availability \
        --workers 20 \
        --batch-size 100 \
        --timeout 7
    echo "==> [$(date -u)] Availability check complete"
}

if [ "${AVAILABILITY_LOOP}" = "1" ]; then
    # Long-running worker mode: run every 4 hours indefinitely
    while true; do
        run_check || echo "==> [$(date -u)] Check failed (will retry in 4 hours)"
        echo "==> Sleeping 14400s until next check..."
        sleep 14400
    done
else
    # Single-run mode (cron service calls this once per schedule)
    run_check
fi
