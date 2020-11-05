from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods, require_GET

from NEMO.admin import BuddyRequestForm
from NEMO.models import BuddyRequest, Tool


@login_required
@require_GET
def buddy_system(request):
	buddy_requests = BuddyRequest.objects.filter(expired=False, deleted=False).order_by('start')
	return render(request, 'buddy_system/buddy_system.html', {'buddy_requests': buddy_requests})


@login_required
@require_http_methods(['GET', 'POST'])
def create_buddy_request(request, request_id=None):
	try:
		buddy_request = BuddyRequest.objects.get(id=request_id)
	except BuddyRequest.DoesNotExist:
		buddy_request = None

	dictionary = {
		'tools': Tool.objects.filter(visible=True),
	}

	if request.method == 'POST':
		form = BuddyRequestForm(request.POST, instance=buddy_request)
		if buddy_request and (buddy_request.user != request.user or request.user.is_staff):
			return render(request, 'buddy_system/buddy_request.html', dictionary)
		form.fields['user'].required = False
		form.fields['creation_time'].required = False
		if form.is_valid():
			form.instance.user = request.user
			form.save()
			return redirect('buddy_system')
		else:
			dictionary['form'] = form
			return render(request, 'buddy_system/buddy_request.html', dictionary)
	else:
		form = BuddyRequestForm(instance=buddy_request)
		form.user = request.user
		dictionary['form'] = form
		return render(request, 'buddy_system/buddy_request.html', dictionary)


@login_required
@require_GET
def delete_buddy_request(request, request_id):
	buddy_request = get_object_or_404(BuddyRequest, id=request_id)
	if buddy_request.user == request.user:
		buddy_request.deleted = True
		buddy_request.save(update_fields=['deleted'])
		return redirect('buddy_system')
	else:
		return HttpResponseBadRequest("You are not allowed to delete a request you didn't create.")