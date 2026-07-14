#!/usr/bin/env bash
#
# Deploy tenant-cars (django-tenants, carsexports.com + ~22 tenant domains) to
# its Hetzner VPS #3. The VPS app at /opt/tenant-cars is NOT a git checkout —
# code is shipped by rsync. This script pushes to GitHub (history/backup),
# rsyncs the source, installs deps (uv), runs migrations across ALL schemas,
# collectstatic, and restarts gunicorn.
#
# Usage:
#   ./deploy.sh                 # rsync current working tree + deploy
#   ./deploy.sh "commit msg"    # commit all changes with msg, push, then deploy
#
# Notes:
# - Multi-tenant: migrate_schemas migrates the shared (public) apps AND every
#   tenant schema, so tenant-app migrations are applied everywhere.
# - No --delete: the VPS holds server-only files (gunicorn.ctl, caches, .env,
#   tenant media/staticfiles). Source files deleted locally are NOT auto-removed
#   on the server — remove those by hand if needed.
# - settings_vps load_dotenv's /opt/tenant-cars/.env, so manage.py just needs
#   DJANGO_SETTINGS_MODULE + HOME (no systemd-run gymnastics).
#
set -euo pipefail

VPS_HOST="root@142.132.232.37"
VPS_KEY="$HOME/.ssh/hetzner_key"
VPS_APP="/opt/tenant-cars"
APP_USER="tenant"
GIT_REMOTE="github"                 # this repo's remote is 'github', not 'origin'
DJ_SETTINGS="cars_multi_site.settings_vps"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SSH="ssh -i $VPS_KEY -o ConnectTimeout=25"

cd "$LOCAL_DIR"

# 1. Optional commit, then push to GitHub -------------------------------------
if [[ $# -ge 1 && -n "$1" ]]; then
  git add -A
  git commit -m "$1" || echo "  (nothing to commit)"
fi
echo "==> Pushing to GitHub ($GIT_REMOTE main)"
git push "$GIT_REMOTE" main

# 2. rsync source to the VPS (no --delete; excludes VPS-specific/user data) ----
echo "==> Syncing source to $VPS_HOST:$VPS_APP"
rsync -az \
  --rsh="$SSH" \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='.env' --exclude='*.env' \
  --exclude='.cache/' --exclude='.local/' --exclude='.claude/' \
  --exclude='.happycar_cache/' --exclude='.happycar_cookie' \
  --exclude='staticfiles/' --exclude='media/' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='db.sqlite3' --exclude='*.sql' --exclude='*.dump' \
  --exclude='.translations_cache.json' \
  --exclude='gunicorn.ctl' --exclude='run_cron_import.sh' \
  ./ "$VPS_HOST:$VPS_APP/"

# 3. Server-side: deps, migrate (all schemas), collectstatic, restart ---------
echo "==> Running server-side deploy steps"
$SSH "$VPS_HOST" bash -s <<REMOTE
set -euo pipefail
chown -R $APP_USER:$APP_USER $VPS_APP
run_mgr() {
  sudo -u $APP_USER env HOME=$VPS_APP DJANGO_SETTINGS_MODULE=$DJ_SETTINGS \
    $VPS_APP/.venv/bin/python $VPS_APP/manage.py "\$@"
}
# deps (uv-managed venv; no pip shim)
sudo -u $APP_USER env HOME=$VPS_APP bash -c "cd $VPS_APP && /usr/local/bin/uv pip install -q -r requirements.txt"
# migrate shared (public) apps + every tenant schema
run_mgr migrate_schemas
run_mgr collectstatic --noinput
systemctl restart tenant.service
systemctl is-active tenant.service
REMOTE

echo "==> Deployed. https://carsexports.com + tenant domains are on the new build."
