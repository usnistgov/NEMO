# This is the default Gunicorn configuration file for the NEMO Docker image.
# It is mounted inside the image at /etc/gunicorn_configuration.py, and you can override it by
# mounting your own configuration file to this location or providing command line arguments to Gunicorn.

from multiprocessing import cpu_count

bind = "0.0.0.0:8000"
worker_class = "gthread"
# The following value was decided based on the Gunicorn documentation and configuration example:
# http://docs.gunicorn.org/en/stable/configure.html#configuration-file
workers = min(cpu_count() * 2 + 1, 9)
threads = 8
keepalive = 300
capture_output = True
