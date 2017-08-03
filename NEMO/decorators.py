def disable_session_expiry_refresh(f):
	"""
	Security policy dictates that the user's session should time out after a set duration.
	The user's session is automatically refreshed (that is, the expiration date
	of their session is moved forward to 30 minutes after the request time) whenever
	the user performs an action. Pages such as the Calendar, Tool Control, and Status Dashboard
	all have polling AJAX requests to update information on the page. These regular polling
	requests should not refresh the session (because it does not indicate the user took
	an action). Place this decorator on any view that is regularly polled so that the
	user's session is not refreshed.
	"""
	f.disable_session_expiry_refresh = True
	return f
