# This is the default Gunicorn configuration file for the NEMO Docker image.
# It is mounted inside the image at /etc/gunicorn_configuration.py, and you can override it by
# mounting your own configuration file to this location or providing command line arguments to Gunicorn.
import os
from multiprocessing import cpu_count

from NEMO.utilities import strtobool

bind = "0.0.0.0:8000"
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread") or "gthread"
# The following value was decided based on the Gunicorn documentation and configuration example:
# http://docs.gunicorn.org/en/stable/configure.html#configuration-file
workers = int(os.getenv("GUNICORN_WORKER_COUNT", min(cpu_count() * 2 + 1, 9)) or min(cpu_count() * 2 + 1, 9))
threads = int(os.getenv("GUNICORN_THREAD_COUNT", "8") or "8")
keepalive = int(os.getenv("GUNICORN_KEEPALIVE_SECONDS", "300") or "300")
capture_output = bool(strtobool(os.getenv("GUNICORN_CAPTURE_OUTPUT", "True") or "True"))
