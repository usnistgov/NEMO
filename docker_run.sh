#!/bin/bash

# Exit if any of following commands fails
set -e

# Run migrations to create or update the database
django-admin makemigrations NEMO
django-admin migrate

# Collect static files
django-admin collectstatic

# Run NEMO
gunicorn NEMO.wsgi:application