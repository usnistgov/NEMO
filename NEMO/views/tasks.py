from logging import getLogger
from typing import List

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.template.defaultfilters import linebreaksbr
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.forms import TaskForm, nice_errors, TaskImagesForm
from NEMO.models import Interlock, Reservation, SafetyIssue, Task, TaskCategory, TaskHistory, TaskStatus, UsageEvent, TaskImages
from NEMO.utilities import bootstrap_primary_color, format_datetime, send_mail, create_email_attachment, resize_image, EmailCategory
from NEMO.views.customization import get_customization, get_media_file_contents
from NEMO.views.safety import send_safety_email_notification
from NEMO.views.tool_control import determine_tool_status

tasks_logger = getLogger("NEMO.Tasks")


@login_required
@require_POST
def create(request):
	"""
	This function handles feedback from users. This could be a problem report or shutdown notification.
	"""
	images_form = TaskImagesForm(request.POST, request.FILES)
	form = TaskForm(request.user, data=request.POST)
	if not form.is_valid() or not images_form.is_valid():
		errors = nice_errors(form)
		errors.update(nice_errors(images_form))
		dictionary = {
			'title': 'Task creation failed',
			'heading': 'Something went wrong while reporting the problem',
			'content': errors.as_ul(),
		}
		return render(request, 'acknowledgement.html', dictionary)
	task = form.save()
	task_images = save_task_images(request, task)

	if not settings.ALLOW_CONDITIONAL_URLS and task.force_shutdown:
		site_title = get_customization('site_title')
		dictionary = {
			'title': 'Task creation failed',
			'heading': 'Something went wrong while reporting the problem',
			'content': f"Tool control is only available on campus. When creating a task, you can't force a tool shutdown while using {site_title} off campus.",
		}
		return render(request, 'acknowledgement.html', dictionary)

	if task.force_shutdown:
		# Shut down the tool.
		task.tool.operational = False
		task.tool.save()
		# End any usage events in progress for the tool or the tool's children.
		UsageEvent.objects.filter(tool_id__in=task.tool.get_family_tool_ids(), end=None).update(end=timezone.now())
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

	send_new_task_emails(request, task, task_images)
	set_task_status(request, task, request.POST.get('status'), request.user)
	return redirect('tool_control')


def send_new_task_emails(request, task: Task, task_images: List[TaskImages]):
	message = get_media_file_contents('new_task_email.html')
	attachments = None
	if task_images:
		attachments = [create_email_attachment(task_image.image, task_image.image.name) for task_image in task_images]
	# Send an email to the appropriate staff that a new task has been created:
	if message:
		dictionary = {
			'template_color': bootstrap_primary_color('danger') if task.force_shutdown else bootstrap_primary_color('warning'),
			'user': request.user,
			'task': task,
			'tool': task.tool,
			'tool_control_absolute_url': request.build_absolute_uri(task.tool.get_absolute_url())
		}
		subject = ('SAFETY HAZARD: ' if task.safety_hazard else '') + task.tool.name + (' shutdown' if task.force_shutdown else ' problem')
		message = Template(message).render(Context(dictionary))
		managers = []
		if hasattr(settings, 'LAB_MANAGERS'):
			managers = settings.LAB_MANAGERS
		recipients = tuple([r for r in [task.tool.primary_owner.email, *task.tool.backup_owners.all().values_list('email', flat=True), task.tool.notification_email_address, *managers] if r])
		send_mail(subject=subject, content=message, from_email=request.user.email, to=recipients, attachments=attachments, email_category=EmailCategory.TASKS)

	# Send an email to any user (excluding staff) with a future reservation on the tool:
	user_office_email = get_customization('user_office_email_address')
	message = get_media_file_contents('reservation_warning_email.html')
	if user_office_email and message:
		upcoming_reservations = Reservation.objects.filter(start__gt=timezone.now(), cancelled=False, tool=task.tool, user__is_staff=False)
		for reservation in upcoming_reservations:
			if not task.tool.operational:
				subject = reservation.tool.name + " reservation problem"
				rendered_message = Template(message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('danger'), 'fatal_error': True}))
			else:
				subject = reservation.tool.name + " reservation warning"
				rendered_message = Template(message).render(Context({'reservation': reservation, 'template_color': bootstrap_primary_color('warning'), 'fatal_error': False}))
			reservation.user.email_user(subject=subject, content=rendered_message, from_email=user_office_email, email_category=EmailCategory.TASKS)


@login_required
@require_POST
def cancel(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	if task.cancelled or task.resolved:
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
	task.cancelled = True
	task.resolver = request.user
	task.resolution_time = timezone.now()
	task.save()
	determine_tool_status(task.tool)
	send_task_updated_email(task, request.build_absolute_uri(task.tool.get_absolute_url()))
	return redirect('tool_control')


def send_task_updated_email(task, url, task_images: List[TaskImages] = None):
	try:
		if not hasattr(settings, 'LAB_MANAGERS'):
			return
		attachments = None
		if task_images:
			attachments = [create_email_attachment(task_image.image, task_image.image.name) for task_image in task_images]
		task.refresh_from_db()
		if task.cancelled:
			task_user = task.resolver
			task_status = 'cancelled'
		elif task.resolved:
			task_user = task.resolver
			task_status = 'resolved'
		else:
			task_user = task.last_updated_by
			task_status = 'updated'
		message = f"""
A task for the {task.tool} was just modified by {task_user}.
<br/><br/>
The latest update is at the bottom of the description. The entirety of the task status follows: 
<br/><br/>
Task problem description:<br/>
{linebreaksbr(task.problem_description)}
<br/><br/>
Task progress description:<br/>
{linebreaksbr(task.progress_description)}
<br/><br/>
Task resolution description:<br/>
{linebreaksbr(task.resolution_description)}
<br/><br/>
Visit {url} to view the tool control page for the task.<br/>
"""
		send_mail(subject=f'{task.tool} task {task_status}', content=message, from_email=settings.SERVER_EMAIL, to=settings.LAB_MANAGERS, attachments=attachments, email_category=EmailCategory.TASKS)
	except Exception as error:
		site_title = get_customization('site_title')
		error_message = f"{site_title} was unable to send the task updated email. The error message that was received is: " + str(error)
		tasks_logger.exception(error_message)


@staff_member_required(login_url=None)
@require_POST
def update(request, task_id):
	task = get_object_or_404(Task, id=task_id)
	images_form = TaskImagesForm(request.POST, request.FILES)
	form = TaskForm(request.user, data=request.POST, instance=task)
	next_page = request.POST.get('next_page', 'tool_control')
	if not form.is_valid() or not images_form.is_valid():
		errors = nice_errors(form)
		errors.update(nice_errors(images_form))
		dictionary = {
			'title': 'Task update failed',
			'heading': 'Invalid task form data',
			'content': errors.as_ul(),
		}
		return render(request, 'acknowledgement.html', dictionary)
	form.save()
	set_task_status(request, task, request.POST.get('status'), request.user)
	determine_tool_status(task.tool)
	task_images = save_task_images(request, task)
	send_task_updated_email(task, request.build_absolute_uri(task.tool.get_absolute_url()), task_images)
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
		'task_statuses': TaskStatus.objects.all(),
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


def set_task_status(request, task, status_name, user):
	if not status_name:
		return

	if not user.is_staff:
		raise ValueError("Only staff can set task status")

	status = TaskStatus.objects.get(name=status_name)
	TaskHistory.objects.create(task=task, status=status_name, user=user)

	status_message = f'On {format_datetime(timezone.now())}, {user.get_full_name()} set the status of this task to "{status_name}".'
	task.progress_description = status_message if task.progress_description is None else task.progress_description + '\n\n' + status_message
	task.save()

	message = get_media_file_contents('task_status_notification.html')
	# Send an email to the appropriate staff that a task status has been updated:
	if message:
		dictionary = {
			'template_color': bootstrap_primary_color('success'),
			'title': f'{task.tool} task notification',
			'status_message': status_message,
			'notification_message': status.notification_message,
			'task': task,
			'tool_control_absolute_url': request.build_absolute_uri(task.tool.get_absolute_url())
		}
		subject = f'{task.tool} task notification'
		message = Template(message).render(Context(dictionary))
		recipients = [
			task.tool.primary_tool_owner.email if status.notify_primary_tool_owner else None,
			task.tool.notification_email_address if status.notify_tool_notification_email else None,
			status.custom_notification_email_address
		]
		if status.notify_backup_tool_owners:
			recipients += task.tool.backup_tool_owners.values_list('email')
		recipients = filter(None, recipients)
		send_mail(subject=subject, content=message, from_email=user.email, to=recipients, email_category=EmailCategory.TASKS)


def save_task_images(request, task: Task) -> List[TaskImages]:
	task_images: List[TaskImages] = []
	try:
		images_form = TaskImagesForm(request.POST, request.FILES)
		if images_form.is_valid() and images_form.cleaned_data['image'] is not None:
			for image_memory_file in request.FILES.getlist('image'):
				resized_image = resize_image(image_memory_file, 350)
				image = TaskImages(task=task)
				image.image.save(resized_image.name, ContentFile(resized_image.read()), save=False)
				image.save()
				task_images.append(image)
	except Exception as e:
		tasks_logger.exception(e)
	return task_images
