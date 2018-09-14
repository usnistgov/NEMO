#!/bin/bash

# Exit if any of following commands fails
set -e

# Run migrations to create or update the database
django-admin migrate

# Collect static files
django-admin collectstatic --no-input --clear

# Run NEMO
gunicorn --config=/nemo/gunicorn_configuration.py NEMO.wsgi:application