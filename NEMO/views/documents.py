from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET

supported_embedded_video_extensions = [".mp4", ".ogv", ".webm", ".3gp"]
supported_embedded_pdf_extensions = [".pdf"]
supported_embedded_extensions = supported_embedded_pdf_extensions + supported_embedded_video_extensions


@login_required
@require_GET
def media_view(request, popup, document_type, document_id):
	document = None
	if document_type == "safety_document":
		from NEMO.models import SafetyItemDocuments

		document = get_object_or_404(SafetyItemDocuments, id=document_id)
	video = any([document.link().lower().endswith(ext) for ext in supported_embedded_video_extensions])
	pdf = any([document.link().lower().endswith(ext) for ext in supported_embedded_pdf_extensions])
	if not video and not pdf:
		return HttpResponseBadRequest(mark_safe(f'Unsupported file format. Click <a href="{document.link()}" target="_blank">here</a> to download the document'))
	dictionary = {
		"popup_view": popup,
		"document": document,
		"controls": True,
		"autoplay": False,
		"video": video,
		"pdf": pdf,
	}
	return render(request, "snippets/embedded_document.html", dictionary)
