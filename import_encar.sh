#!/usr/bin/env bash
# Usage:
#   ./import_encar.sh                    # imports today's date
#   ./import_encar.sh 2026-03-11         # imports specific date
#   ./import_encar.sh 2026-03-11 --dry-run
#   ./import_encar.sh 2026-03-11 --skip-removed

DATE="${1:-$(date +%Y-%m-%d)}"
shift 2>/dev/null   # remove $1 so remaining args pass through

DATABASE_URL="postgresql://postgres:gBxXJaMReZkNXJRzsbUmZjfZqWwqRGsM@turntable.proxy.rlwy.net:39566/railway" \
ENCAR_HOST="https://autobase-berger.auto-parser.ru" \
ENCAR_USER="admin" \
ENCAR_PASS="01wyvD2fRpctTfm17tgx" \
SECRET_KEY="f2lDbrwpRVfSzLpIbCRPfZp7j399a6rwly5oUnoac3cZPQwrsjQEHyKvzli8ZQCPwzU" \
DEBUG=True \
ALLOWED_HOSTS="*" \
.venv/bin/python manage.py import_encar_fast --date "$DATE" --progress "$@"
