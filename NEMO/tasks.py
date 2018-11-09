from atexit import register
from logging import getLogger
from queue import Queue
from threading import Thread

postponed_tasks_logger = getLogger("NEMO.PostponedTasks")


def postpone(function):
	def decorator(*arguments, **named_arguments):
		_queue.put((function, arguments, named_arguments))
	return decorator


def _worker():
	while True:
		function, arguments, named_arguments = _queue.get()
		try:
			function(*arguments, **named_arguments)
		except:
			from traceback import format_exc
			details = format_exc()
			postponed_tasks_logger.exception(details)
		finally:
			_queue.task_done()  # So we can join at exit


def _cleanup():
	_queue.join()  # So we don't exit too soon


_queue = Queue()
_thread = Thread(target=_worker, name='Postponed execution thread')
_thread.daemon = True
_thread.start()
register(_cleanup)
