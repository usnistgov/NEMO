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
# If PUID is not 0 (root)
if [ -n "$PUID" ]; then
    # Change the user and group IDs
    usermod -u "$PUID" -g "$PGID" nemo
    # Change the ownership of the application directory
    chown -R nemo:nemo /nemo
    chown -R root:nemo /etc/gunicorn_configuration.py
    NEMO_USER=nemo
else
    NEMO_USER=root
fi
echo "Running NEMO as user '$(id $NEMO_USER)'"

# Collect static files
su "${NEMO_USER}" -c "django-admin collectstatic --no-input --clear"

# Run migrations to create or update the database
su "${NEMO_USER}" -c "django-admin migrate"

# Run NEMO
su "${NEMO_USER}" -c "exec gunicorn --config=/etc/gunicorn_configuration.py NEMO.wsgi:application"
