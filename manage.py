import os
import sys
from logging import getLogger

manage_logger = getLogger("management_commands")

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
    from django.core.management import execute_from_command_line

    try:
        execute_from_command_line(sys.argv)
    except Exception as e:
        manage_logger.error("%s", " ".join(sys.argv), exc_info=sys.exc_info())
        raise e
