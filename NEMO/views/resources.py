from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_http_methods

from NEMO.models import Resource, UsageEvent, Tool, ResourceCategory


@staff_member_required(login_url=None)
@require_GET
def resources(request):
	dictionary = {
		'resource_categories': ResourceCategory.objects.all()
	}
	return render(request, 'resources/resources.html', dictionary)


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def modify_resource(request, resource_id):
	resource = get_object_or_404(Resource, id=resource_id)
	dictionary = {'resource': resource}
	if request.method == 'GET':
		in_use = set(map(lambda t: t.tool.id, UsageEvent.objects.filter(end=None)))
		fully_dependent_tools = set(map(lambda f: f.id, resource.fully_dependent_tools.all()))
		fully_dependent_tools_in_use = Tool.objects.in_bulk(list(in_use & fully_dependent_tools)).values()
		dictionary['fully_dependent_tools_in_use'] = fully_dependent_tools_in_use
		return render(request, 'resources/modify_resource.html', dictionary)
	elif request.method == 'POST':
		status = request.POST.get('status')
		if status == 'unavailable':
			resource.available = False
			reason = request.POST.get('reason')
			if not reason:
				dictionary['error'] = 'You must explain why the resource is unavailable.'
				return render(request, 'resources/modify_resource.html', dictionary)
			resource.restriction_message = reason
			resource.save()
		elif status == 'available':
			resource.available = True
			resource.save()
		else:
			dictionary['error'] = 'The server received an invalid resource modification request.'
			return render(request, 'resources/modify_resource.html', dictionary)
		return redirect('resources')
