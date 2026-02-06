release: python manage.py migrate
web: python manage.py collectstatic --noinput && gunicorn config.wsgi:application