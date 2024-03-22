#!/bin/bash

# Exit if any of following commands fails
set -e

# Collect static files
django-admin collectstatic --no-input --clear

# Run migrations to create or update the database
django-admin migrate

# Run NEMO
exec gunicorn --config=/etc/gunicorn_configuration.py NEMO.wsgi:application
