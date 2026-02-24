web: gunicorn cars_multi_site.wsgi --log-file - --max-requests 500 --max-requests-jitter 50 --preload --workers 1 --threads 3 --timeout 20
release: python manage.py migrate --noinput