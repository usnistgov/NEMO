from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from NEMO.forms import ScheduledOutageForm
from NEMO.models import Resource, UsageEvent, Tool, ScheduledOutage, ScheduledOutageCategory


@staff_member_required(login_url=None)
@require_GET
def resources(request):
	return render(request, 'resources/resources.html', {'resources': Resource.objects.all().order_by('category', 'name')})


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


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def schedule_outage(request):
	outage_id = request.GET.get('outage_id') or request.POST.get('outage_id')
	try:
		outage = ScheduledOutage.objects.get(id=outage_id)
	except:
		outage = None
	if request.method == 'GET':
		form = ScheduledOutageForm(instance=outage)
	elif request.method == 'POST':
		form = ScheduledOutageForm(data=request.POST, instance=outage)
		if form.is_valid():
			outage = form.save(commit=False)
			outage.creator = request.user
			outage.title = f"{outage.resource.name} scheduled outage"
			outage.save()
			form = ScheduledOutageForm()
	else:
		form = ScheduledOutageForm()
	dictionary = {
		'form': form,
		'editing': True if form.instance.id else False,
		'resources': Resource.objects.all().prefetch_related('category').order_by('category__name', 'name'),
		'outages': ScheduledOutage.objects.filter(resource__isnull=False),
		'outage_categories': ScheduledOutageCategory.objects.all(),
	}
	return render(request, 'resources/scheduled_outage.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def delete_scheduled_outage(request, outage_id):
	try:
		ScheduledOutage.objects.filter(id=outage_id).delete()
	except Http404:
		pass
	return redirect(request.META.get('HTTP_REFERER', 'landing'))
