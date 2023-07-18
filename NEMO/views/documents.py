from __future__ import annotations

import io
import zipfile
from typing import List

import requests
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import BaseDocumentModel
from NEMO.utilities import (
	export_format_datetime,
	supported_embedded_pdf_extensions,
	supported_embedded_video_extensions,
)


@login_required
@require_GET
def media_view(request, popup, content_type_id, document_id):
	content_type = ContentType.objects.get_for_id(content_type_id)
	document = get_object_or_404(content_type.model_class(), pk=document_id)
	video = any([document.link().lower().endswith(ext) for ext in supported_embedded_video_extensions])
	pdf = any([document.link().lower().endswith(ext) for ext in supported_embedded_pdf_extensions])
	if not video and not pdf:
		return HttpResponseBadRequest(
			mark_safe(
				f'Unsupported file format. Click <a href="{document.link()}" target="_blank">here</a> to download the document'
			)
		)
	dictionary = {
		"popup_view": popup == "true",
		"document": document,
		"controls": True,
		"autoplay": False,
		"video": video,
		"pdf": pdf,
	}
	return render(request, "snippets/embedded_document.html", dictionary)


@login_required
@require_POST
def media_list_view(request, allow_zip, popup):
	documents = get_documents_from_post(request)
	title = request.POST.get("title")
	return document_list_view(request, documents, title, allow_zip == "true", popup == "true")


def document_list_view(request, document_list: List[BaseDocumentModel], title=None, allow_zip=True, popup=True):
	return render(
		request,
		"snippets/document_list.html",
		{"document_list": document_list, "title": title, "allow_zip": allow_zip, "popup_view": popup},
	)


@login_required
@require_POST
def media_zip(request):
	documents = get_documents_from_post(request)
	if not documents:
		return HttpResponse()
	parent_folder_name = f"documents_{export_format_datetime()}"
	zip_io = io.BytesIO()
	with zipfile.ZipFile(zip_io, mode="w", compression=zipfile.ZIP_DEFLATED) as document_zip:
		for document in documents:
			file_name = f"{parent_folder_name}/" + document.filename()
			if document.document and document.document.path:
				document_zip.write(document.document.path, file_name)
			elif document.url:
				document_response = requests.get(document.url)
				if document_response.ok:
					document_zip.writestr(file_name, document_response.content)
	response = HttpResponse(zip_io.getvalue(), content_type="application/x-zip-compressed")
	response["Content-Disposition"] = "attachment; filename=%s" % parent_folder_name + ".zip"
	response["Content-Length"] = zip_io.tell()
	return response


def get_documents_from_post(request) -> List[BaseDocumentModel]:
	documents: List[BaseDocumentModel] = []
	document_infos = request.POST.getlist("document_info", [])
	for document_info in document_infos:
		info = document_info.split("__")
		content_type_id, document_id = info[0], info[1]
		content_type = ContentType.objects.get_for_id(content_type_id)
		try:
			documents.append(content_type.model_class().objects.get(pk=document_id))
		except content_type.model_class().DoesNotExist:
			pass
	return documents
