#!/bin/bash

# Exit if any of following commands fails
set -e

if [[ -n "$NEMO_EXTRA_PIP_PACKAGES" ]]; then
    echo "Installing additional Python packages: $NEMO_EXTRA_PIP_PACKAGES"
    python3 -m pip install $NEMO_EXTRA_PIP_PACKAGES
else
    echo "No additional Python packages to install."
fi

# Collect static files
django-admin collectstatic --no-input --clear

# Run migrations to create or update the database
django-admin migrate

# Run NEMO
exec gunicorn --config=/etc/gunicorn_configuration.py NEMO.wsgi:application
