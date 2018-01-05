#!/bin/bash

# Exit if any of following commands fails
set -e

# Check if BIND_ADDR is set. If not, set a default one.
if [[ -z "${BIND_ADDR}" ]]; then
    export BIND_ADDR=0.0.0.0:9000
fi

# NEMO settings env variable (default setting to use)
if [[ -z "${DJANGO_SETTINGS_MODULE}" ]]; then
    export DJANGO_SETTINGS_MODULE=NEMO.settings.dev_unsecure
fi 

# Run migrations
django-admin makemigrations NEMO
django-admin migrate

# Copy static files
django-admin collectstatic

# Run NEMO
gunicorn --bind $BIND_ADDR NEMO.wsgi:application
