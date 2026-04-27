web: gunicorn cars_multi_site.wsgi --log-file - --access-logfile - --access-logformat '%(h)s "%(r)s" %(s)s %(b)s "%(a)s" %({x-forwarded-for}i)s %(L)s' --max-requests 500 --max-requests-jitter 50 --preload --workers 2 --threads 4 --worker-class gthread --timeout 60 --bind 0.0.0.0:${PORT:-8000}
release: bash release.sh
import_encar: python manage.py import_encar_fast --date ${IMPORT_DATE:-$(date +%Y-%m-%d)} --progress
