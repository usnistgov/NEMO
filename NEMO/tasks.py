from logging import getLogger
from threading import Thread

postponed_tasks_logger = getLogger("NEMO.PostponedTasks")


def postpone(function):
	def decorator(*arguments, **named_arguments):
		t = Thread(target=function, args=arguments, kwargs=named_arguments)
		t.daemon = True
		t.start()
	return decorator
