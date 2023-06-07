from logging import getLogger

import requests
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import NotFound

from NEMO.utilities import get_full_url, render_combine_responses

api_logger = getLogger(__name__)


@require_http_methods(["GET", "POST"])
@csrf_exempt
def file_import(request):
	if request.method == "GET":
		return redirect("api-root")
	url = None
	headers = get_new_headers(request)
	try:
		url = get_full_url(request.POST["request_url"], request)
		import_file = request.FILES.get("import_file")
		if not import_file:
			raise NotFound("Please upload a file")
		data = import_file.read()
		headers["Content-Type"] = import_file.content_type
		response = requests.post(url, data, headers=headers, cookies=request.COOKIES, allow_redirects=False)
		# Deal with potential redirect here by resubmitting
		if response.status_code == 301:
			response = requests.post(response.headers["Location"], data, headers=headers, cookies=request.COOKIES)
		return HttpResponse(
			response.content, status=response.status_code, content_type=response.headers["Content-Type"]
		)
	except Exception as e:
		api_logger.exception("Error processing API file import")
		if url:
			# This is a bit of a hack to display an error message, using the OPTIONS request method and changing the content
			status_code = getattr(e, "status_code", 400)
			response = requests.options(url, headers=headers)
			template_response = HttpResponse(
				response.content, status=status_code, content_type=response.headers["Content-Type"]
			)
			context = {
				"error": str(e),
				"status_code": template_response.status_code,
				"status_text": template_response.reason_phrase,
			}
			return render_combine_responses(request, template_response, "rest_framework/custom_error.html", context)
		else:
			raise


def get_new_headers(request):
	headers = {key: value for key, value in request.headers.items()}
	# Put new csrf in the correct header
	new_csrf = request.POST["csrfmiddlewaretoken"]
	csrf_header_name = settings.CSRF_HEADER_NAME
	if csrf_header_name.startswith("HTTP_"):
		csrf_header_name = csrf_header_name[5:]
	csrf_header_name = csrf_header_name.replace("_", "-")
	headers[csrf_header_name] = new_csrf
	return headers
