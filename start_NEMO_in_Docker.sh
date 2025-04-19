#!/bin/bash
# Exit if any of following commands fails
set -e

if [[ -n "$NEMO_EXTRA_PIP_PACKAGES" ]]; then
    echo "Installing additional Python packages: $NEMO_EXTRA_PIP_PACKAGES"
    python3 -m pip install $NEMO_EXTRA_PIP_PACKAGES
else
    echo "No additional Python packages to install."
fi

# Set the PUID and PGID environment variables
PUID=${PUID:-963}
PGID=${PGID:-963}
# Change the user and group IDs
groupmod -o -g "$PGID" nemo
usermod -o -u "$PUID" -g "$PGID" nemo
if [ -n "$PUID" ]; then
    # Change the ownership of the application directory
    chown -R nemo:nemo /nemo
    chown -R root:nemo /etc/gunicorn_configuration.py
fi
echo "Running NEMO as user '$(id nemo)'"

# Collect static files
su nemo -c "django-admin collectstatic --no-input --clear"

# Run migrations to create or update the database
su nemo -c "django-admin migrate"

# Run NEMO
exec su nemo -c "gunicorn --config=/etc/gunicorn_configuration.py NEMO.wsgi:application"
