from logging import getLogger

import requests
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import NotFound

from NEMO.utilities import get_full_url, render_combine_responses

api_logger = getLogger(__name__)


@require_http_methods(["GET", "POST"])
@login_required
@csrf_exempt
def file_import(request):
	if request.method == "GET":
		return redirect("api-root")
	url = None
	try:
		url = get_full_url(request.POST["request_url"], request)
		if "import_file" not in request.FILES:
			raise NotFound("Please upload a file")
		data = request.FILES.get("import_file").read()
		response = requests.post(url, data, headers=get_new_headers(request))
		return HttpResponse(
			response.content, status=response.status_code, content_type=response.headers["Content-Type"]
		)
	except Exception as e:
		api_logger.exception("Error processing API file import")
		if url:
			# This is a bit of a hack to display an error message, using the OPTIONS request method and changing the content
			status_code = getattr(e, "status_code", 400)
			response = requests.options(url, headers=get_new_headers(request))
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
	headers["X-csrftoken"] = request.POST["csrfmiddlewaretoken"]
	if "import_file" in request.FILES:
		headers["Content-Type"] = request.FILES.get("import_file").content_type
	return headers
