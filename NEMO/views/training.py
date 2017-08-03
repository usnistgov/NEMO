from re import search

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import User, Tool, TrainingSession, Project, MembershipHistory


@staff_member_required(login_url=None)
@require_GET
def training(request):
	""" Present a web page to allow staff to charge training and qualify users on particular tools. """
	users = User.objects.filter(is_active=True).exclude(id=request.user.id)
	tools = Tool.objects.filter(visible=True)
	return render(request, 'training/training.html', {'users': users, 'tools': tools, 'charge_types': TrainingSession.Type.Choices})


@staff_member_required(login_url=None)
@require_GET
def training_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'training/training_entry.html', {'entry_number': entry_number, 'charge_types': TrainingSession.Type.Choices})


def is_valid_field(field):
	return search("^(chosen_user|chosen_tool|chosen_project|duration|charge_type|qualify)__[0-9]+$", field) is not None


@staff_member_required(login_url=None)
@require_POST
def charge_training(request):
	try:
		charges = {}
		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in charges:
					charges[index] = TrainingSession()
					charges[index].trainer = request.user
				if attribute == "chosen_user":
					charges[index].trainee = User.objects.get(id=value)
				if attribute == "chosen_tool":
					charges[index].tool = Tool.objects.get(id=value)
				if attribute == "chosen_project":
					charges[index].project = Project.objects.get(id=value)
				if attribute == "duration":
					charges[index].duration = int(value)
				if attribute == "charge_type":
					charges[index].type = int(value)
				if attribute == "qualify":
					charges[index].qualified = (value == "on")
		for c in charges.values():
			c.full_clean()
	except Exception:
		return HttpResponseBadRequest('An error occurred while processing the training charges. None of the charges were committed to the database. Please review the form for errors and omissions then submit the form again.')
	else:
		for c in charges.values():
			if c.qualified:
				qualify(c.trainer, c.trainee, c.tool)
			c.save()
		dictionary = {
			'title': 'Success!',
			'content': 'Training charges were successfully saved.',
			'redirect': '/',
		}
		return render(request, 'display_success_and_redirect.html', dictionary)


def qualify(authorizer, user, tool):
	if tool in user.qualifications.all():
		return
	user.qualifications.add(tool)
	entry = MembershipHistory()
	entry.authorizer = authorizer
	entry.parent_content_object = tool
	entry.child_content_object = user
	entry.action = entry.Action.ADDED
	entry.save()
