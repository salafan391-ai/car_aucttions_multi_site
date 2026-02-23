web: gunicorn cars_multi_site.wsgi --log-file - --max-requests 1000 --max-requests-jitter 100 --preload --workers 2 --threads 2 --timeout 25
release: python manage.py migrate --noinput