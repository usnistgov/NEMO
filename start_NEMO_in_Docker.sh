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
if [ "$PGID" -eq 0 ]; then
    # If PGID is 0, use the root group
    NEMO_GROUP="root"
else
    NEMO_GROUP="nemo"
    groupmod -g "$PGID" "$NEMO_GROUP"
fi
if [ "$PUID" -eq 0 ]; then
    # If PUID is 0, use the root user
    NEMO_USER="root"
else
    NEMO_USER="nemo"
    usermod -u "$PUID" "$NEMO_USER"
fi

# Change the ownership of the application directory
if [ "$PUID" -ne 0 ]; then
  chown -R nemo:nemo /nemo
  chown -R root:nemo /etc/gunicorn_configuration.py
fi
echo "Running NEMO as user '${NEMO_USER}' (uid: ${PUID}), primary group '${NEMO_GROUP}' (gid: ${PGID})"

# Collect static files
su "${NEMO_USER}" -g "${NEMO_GROUP}" -c "django-admin collectstatic --no-input --clear"

# Run migrations to create or update the database
su ${NEMO_USER} -c "django-admin migrate"

# Run NEMO
su ${NEMO_USER} -c "exec gunicorn --config=/etc/gunicorn_configuration.py NEMO.wsgi:application"
