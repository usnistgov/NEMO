from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, render, redirect
from django.template import Template, Context
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from NEMO.forms import TaskForm, nice_errors
from NEMO.models import Task, UsageEvent, Interlock, TaskCategory, Reservation, SafetyIssue
from NEMO.utilities import bootstrap_primary_color
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.safety import send_safety_email_notification
from NEMO.views.tool_control import determine_tool_status


@login_required
@require_POST
def create(request):
	"""
	This function handles feedback from users. This could be a problem report or shutdown notification.
	"""
	form = TaskForm(request.user, data=request.POST)
	if not form.is_valid():
		dictionary = {
			'title': 'Task creation failed',
			'heading': 'Something went wrong while reporting the problem',
			'content': nice_errors(form).as_ul(),
		}
		return render(request, 'acknowledgement.html', dictionary)
	task = form.save()

	if not settings.ALLOW_CONDITIONAL_URLS and task.force_shutdown:
		dictionary = {
			'title': 'Task creation failed',
			'heading': 'Something went wrong while reporting the problem',
			'content': "Tool control is only available on campus. When creating a task, you can't force a tool shutdown while using NEMO off campus.",
		}
		return render(request, 'acknowledgement.html', dictionary)

	if task.force_shutdown:
		# Shut down the tool.
		task.tool.operational = False
		task.tool.save()
		# End any usage events in progress for the tool.
		UsageEvent.objects.filter(tool=task.tool, end=None).update(end=timezone.now())
		# Lock the interlock for this tool.
		try:
			tool_interlock = Interlock.objects.get(tool__id=task.tool.id)
			tool_interlock.lock()
		except Interlock.DoesNotExist:
			pass

	if task.safety_hazard:
		concern = 'This safety issue was automatically created because a ' + str(task.tool).lower() + ' problem was identified as a safety hazard.\n\n'
		concern += task.problem_description
		issue = SafetyIssue.objects.create(reporter=request.user, location=task.tool.location, concern=concern)
		send_safety_email_notification(request, issue)

	send_new_task_emails(request, task)
	return redirect('tool_control')


def send_new_task_emails(request, task):
	message = get_media_file_contents('new_task_email.html')
	if message:
		dictionary = {
			'template_color': bootstrap_primary_color('danger') if task.force_shutdown else bootstrap_primary_color('warning'),
			'user': request.user,
			'task': task,
			'tool': task.tool,
			'tool_control_absolute_url': request.build_absolute_uri(task.tool.get_absolute_url())
		}
		# Send an email to the appropriate NanoFab staff that a new task has been created:
		subject = ('SAFETY HAZARD: ' if task.safety_hazard else '') + task.tool.name + (' shutdown' if task.force_shutdown else ' problem')
		message = Template(message).render(Context(dictionary))
		recipients = tuple([r for r in [task.tool.primary_owner.email, task.tool.secondary_owner.email, task.tool.notification_email_address] if r])
		send_mail(subject, '', request.user.email, recipients, html_message=message)

	# Send an email to any user (excluding staff) with a future reservation on the tool:
	user_office_email = get_customization('user_office_email_address')
	message = get_media_file_contents('new_task_email.html')
	if user_office_email and message:
		upcoming_reservations = Reservation.objects.filter(start__gt=timezone.now(), cancelled=False, tool=task.tool, user__is_staff=False)
		for reservation in upcoming_reservations:
			if not task.tool.operational:
				subject = reservation.tool.name + " reservation problem"
				rendered_message = Template(message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('danger'), 'fatal_error': True}))
			else:
				subject = reservation.tool.name + " reservation warning"
				rendered_message = Template(message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('warning'), 'fatal_error': False}))
			reservation.user.email_user(subject, rendered_message, user_office_email)


@login_required
@require_POST
def cancel(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	if task.status != Task.Status.REQUIRES_ATTENTION:
		dictionary = {
			'title': 'Task cancellation failed',
			'heading': 'You cannot cancel this task',
			'content': 'The status of this task has been changed so you may no longer cancel it.',
		}
		return render(request, 'acknowledgement.html', dictionary)
	if task.creator.id != request.user.id:
		dictionary = {
			'title': 'Task cancellation failed',
			'heading': 'You cannot cancel this task',
			'content': 'You may only cancel a tasks that you created.',
		}
		return render(request, 'acknowledgement.html', dictionary)
	task.status = Task.Status.CANCELLED
	task.resolver = request.user
	task.resolution_time = timezone.now()
	task.save()
	determine_tool_status(task.tool)
	return redirect('tool_control')


@staff_member_required(login_url=None)
@require_POST
def update(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	form = TaskForm(request.user, data=request.POST, instance=task)
	next_page = request.POST.get('next_page', 'tool_control')
	if not form.is_valid():
		dictionary = {
			'title': 'Task update failed',
			'heading': 'Invalid task form data',
			'content': str(form.errors),
		}
		return render(request, 'acknowledgement.html', dictionary)
	form.save()
	determine_tool_status(task.tool)
	if next_page == 'maintenance':
		return redirect('maintenance')
	else:
		return redirect('tool_control')


@staff_member_required(login_url=None)
@require_GET
def task_update_form(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	categories = TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT)
	dictionary = {
		'categories': categories,
		'urgency': Task.Urgency.Choices,
		'task': task,
	}
	return render(request, 'tasks/update.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def task_resolution_form(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	categories = TaskCategory.objects.filter(stage=TaskCategory.Stage.COMPLETION)
	dictionary = {
		'categories': categories,
		'task': task,
	}
	return render(request, 'tasks/resolve.html', dictionary)
