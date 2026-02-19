web: gunicorn encar_api.wsgi --log-file - --max-requests 1000 --max-requests-jitter 100 --preload --workers 1
release: python manage.py migrate --noinput