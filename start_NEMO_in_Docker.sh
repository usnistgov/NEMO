#!/bin/bash

# Exit if any of following commands fails
set -e

# Run migrations to create or update the database
django-admin makemigrations NEMO
django-admin migrate

# Collect static files
django-admin collectstatic --no-input --clear

# Run NEMO
gunicorn --bind 0.0.0.0:8000 NEMO.wsgi:application
