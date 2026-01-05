FROM python:3.13

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y less vim

# Intall NEMO (in the current directory) and Gunicorn
COPY . /nemo/
RUN python3 -m pip install /nemo/ gunicorn==23.0.0
RUN rm --recursive --force /nemo/

RUN mkdir /nemo
WORKDIR /nemo
ENV DJANGO_SETTINGS_MODULE="settings"
ENV PYTHONPATH="/nemo/"

# Gunicorn config options
ENV GUNICORN_WORKER_CLASS=""
ENV GUNICORN_WORKER_COUNT=""
ENV GUNICORN_THREAD_COUNT=""
ENV GUNICORN_KEEPALIVE_SECONDS=""
ENV GUNICORN_CAPTURE_OUTPUT=""

# NEMO extra python packages
ENV NEMO_EXTRA_PIP_PACKAGES=""

COPY gunicorn_configuration.py /etc/

EXPOSE 8000/tcp

COPY start_NEMO_in_Docker.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/start_NEMO_in_Docker.sh
# Add non-root user
RUN addgroup --system --gid 963 nemo && \
    adduser --system --home /home/nemo --shell /usr/bin/bash --gid 963 --uid 963  --comment "NEMO user" nemo
CMD ["start_NEMO_in_Docker.sh"]
