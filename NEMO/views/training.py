from logging import getLogger
from re import search
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from NEMO.exceptions import ProjectChargeException
from NEMO.models import User, Tool, TrainingSession, Project, MembershipHistory
from NEMO.tasks import staff_member_or_tool_superuser_required
from NEMO.views.policy import check_billing_to_project
from NEMO.views.users import get_identity_service

training_logger = getLogger(__name__)


@staff_member_or_tool_superuser_required(login_url=None)
@require_GET
def training(request):
	""" Present a web page to allow staff or tool superusers to charge training and qualify users on particular tools. """
	user: User = request.user
	users = User.objects.filter(is_active=True).exclude(id=user.id)
	tools = Tool.objects.filter(visible=True)
	if not user.is_staff and user.is_tool_superuser:
		tools = tools.filter(_superusers__in=[user])
	return render(request, 'training/training.html', {'users': users, 'tools': tools, 'charge_types': TrainingSession.Type.Choices})


@staff_member_or_tool_superuser_required(login_url=None)
@require_GET
def training_entry(request):
	entry_number = int(request.GET['entry_number'])
	return render(request, 'training/training_entry.html', {'entry_number': entry_number, 'charge_types': TrainingSession.Type.Choices})


def is_valid_field(field):
	return search("^(chosen_user|chosen_tool|chosen_project|duration|charge_type|qualify)__[0-9]+$", field) is not None


@staff_member_or_tool_superuser_required(login_url=None)
@require_POST
def charge_training(request):
	trainer: User = request.user
	try:
		charges = {}
		for key, value in request.POST.items():
			if is_valid_field(key):
				attribute, separator, index = key.partition("__")
				index = int(index)
				if index not in charges:
					charges[index] = TrainingSession()
					charges[index].trainer = trainer
				if attribute == "chosen_user":
					charges[index].trainee = User.objects.get(id=to_int_or_negative(value))
				if attribute == "chosen_tool":
					charges[index].tool = Tool.objects.get(id=to_int_or_negative(value))
					if not trainer.is_staff and trainer.is_tool_superuser and charges[index].tool not in trainer.superuser_for_tools.all():
						raise Exception("The trainer is not authorized to train on this tool")
				if attribute == "chosen_project":
					charges[index].project = Project.objects.get(id=to_int_or_negative(value))
				if attribute == "duration":
					charges[index].duration = int(value)
				if attribute == "charge_type":
					charges[index].type = int(value)
				if attribute == "qualify":
					charges[index].qualified = (value == "on")
		for c in charges.values():
			c.full_clean()
			check_billing_to_project(c.project, c.trainee, c.tool)
	except ProjectChargeException as e:
		return HttpResponseBadRequest(e.msg)
	except User.DoesNotExist:
		return HttpResponseBadRequest("Please select a trainee from the list")
	except Tool.DoesNotExist:
		return HttpResponseBadRequest("Please select a tool from the list")
	except Project.DoesNotExist:
		return HttpResponseBadRequest("Please select a project from the list")
	except Exception as e:
		training_logger.exception(e)
		return HttpResponseBadRequest('An error occurred while processing the training charges. None of the charges were committed to the database. Please review the form for errors and omissions then submit the form again.')
	else:
		for c in charges.values():
			if c.qualified:
				qualify(c.trainer, c.trainee, c.tool)
			c.save()
		dictionary = {
			'title': 'Success!',
			'content': 'Training charges were successfully saved.',
			'redirect': reverse('landing'),
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

	if tool.grant_physical_access_level_upon_qualification:
		if tool.grant_physical_access_level_upon_qualification not in user.accessible_access_levels().all():
			user.physical_access_levels.add(tool.grant_physical_access_level_upon_qualification)
			entry = MembershipHistory()
			entry.authorizer = authorizer
			entry.parent_content_object = tool.grant_physical_access_level_upon_qualification
			entry.child_content_object = user
			entry.action = entry.Action.ADDED
			entry.save()

	if get_identity_service().get('available', False):
		if tool.grant_badge_reader_access_upon_qualification:
			parameters = {
				'username': user.username,
				'domain': user.domain,
				'requested_area': tool.grant_badge_reader_access_upon_qualification,
			}
			timeout = settings.IDENTITY_SERVICE.get('timeout', 3)
			requests.put(urljoin(settings.IDENTITY_SERVICE['url'], '/add/'), data=parameters, timeout=timeout)


def to_int_or_negative(value: str):
	try:
		return int(value)
	except ValueError:
		return -1
