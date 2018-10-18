from copy import deepcopy
from datetime import timedelta
from http import HTTPStatus
from itertools import chain

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import logger, require_GET, require_POST

from NEMO.forms import CommentForm, nice_errors
from NEMO.models import Comment, Configuration, ConfigurationHistory, Project, Reservation, StaffCharge, Task, TaskCategory, TaskStatus, Tool, UsageEvent, User
from NEMO.utilities import extract_times, quiet_int
from NEMO.views.policy import check_policy_to_disable_tool, check_policy_to_enable_tool
from NEMO.widgets.dynamic_form import DynamicForm
from NEMO.widgets.tool_tree import ToolTree


@login_required
@require_GET
def tool_control(request, tool_id=None):
	""" Presents the tool control view to the user, allowing them to being/end using a tool or see who else is using it. """
	if request.user.active_project_count() == 0:
		return render(request, 'no_project.html')
	# The tool-choice sidebar is not available for mobile devices, so redirect the user to choose a tool to view.
	if request.device == 'mobile' and tool_id is None:
		return redirect('choose_tool', next_page='tool_control')
	tools = Tool.objects.filter(visible=True).order_by('category', 'name')
	dictionary = {
		'tools': tools,
		'selected_tool': tool_id,
	}
	# The tool-choice sidebar only needs to be rendered for desktop devices, not mobile devices.
	if request.device == 'desktop':
		dictionary['rendered_tool_tree_html'] = ToolTree().render(None, {'tools': tools})
	return render(request, 'tool_control/tool_control.html', dictionary)


@login_required
@require_GET
def tool_status(request, tool_id):
	""" Gets the current status of the tool (that is, whether it is currently in use or not). """
	tool = get_object_or_404(Tool, id=tool_id, visible=True)

	dictionary = {
		'tool': tool,
		'task_categories': TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
		'rendered_configuration_html': tool.configuration_widget(request.user),
		'mobile': request.device == 'mobile',
		'task_statuses': TaskStatus.objects.all(),
		'post_usage_questions': DynamicForm(tool.post_usage_questions).render(),
	}

	try:
		current_reservation = Reservation.objects.get(start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=request.user, tool=tool)
		if request.user == current_reservation.user:
			dictionary['time_left'] = current_reservation.end
	except Reservation.DoesNotExist:
		pass

	# Staff need the user list to be able to qualify users for the tool.
	if request.user.is_staff:
		dictionary['users'] = User.objects.filter(is_active=True)

	return render(request, 'tool_control/tool_status.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def use_tool_for_other(request):
	dictionary = {
		'users': User.objects.filter(is_active=True).exclude(id=request.user.id)
	}
	return render(request, 'tool_control/use_tool_for_other.html', dictionary)


@login_required
@require_POST
def tool_configuration(request):
	""" Sets the current configuration of a tool. """
	try:
		configuration = Configuration.objects.get(id=request.POST['configuration_id'])
	except:
		return HttpResponseNotFound('Configuration not found.')
	if configuration.tool.in_use():
		return HttpResponseBadRequest('Cannot change a configuration while a tool is in use.')
	if not configuration.user_is_maintainer(request.user):
		return HttpResponseBadRequest('You are not authorized to change this configuration.')
	try:
		slot = int(request.POST['slot'])
		choice = int(request.POST['choice'])
	except:
		return HttpResponseBadRequest('Invalid configuration parameters.')
	try:
		configuration.replace_current_setting(slot, choice)
	except IndexError:
		return HttpResponseBadRequest('Invalid configuration choice.')
	configuration.save()
	history = ConfigurationHistory()
	history.configuration = configuration
	history.slot = slot
	history.user = request.user
	history.setting = configuration.get_current_setting(slot)
	history.save()
	return HttpResponse()


@login_required
@require_POST
def create_comment(request):
	form = CommentForm(request.POST)
	if not form.is_valid():
		return HttpResponseBadRequest(nice_errors(form).as_ul())
	comment = form.save(commit=False)
	comment.content = comment.content.strip()
	comment.author = request.user
	comment.expiration_date = None if form.cleaned_data['expiration'] == 0 else timezone.now() + timedelta(days=form.cleaned_data['expiration'])
	comment.save()
	return redirect('tool_control')


@login_required
@require_POST
def hide_comment(request, comment_id):
	comment = get_object_or_404(Comment, id=comment_id)
	if comment.author_id != request.user.id and not request.user.is_staff:
		return HttpResponseBadRequest("You may only hide a comment if you are its author or a staff member.")
	comment.visible = False
	comment.hidden_by = request.user
	comment.hide_date = timezone.now()
	comment.save()
	return redirect('tool_control')


def determine_tool_status(tool):
	# Make the tool operational when all problems are resolved that require a shutdown.
	if tool.task_set.filter(force_shutdown=True, cancelled=False, resolved=False).count() == 0:
		tool.operational = True
	else:
		tool.operational = False
	tool.save()


@login_required
@require_POST
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
	""" Enable a tool for a user. The user must be qualified to do so based on the lab usage policy. """

	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest('Tool control is only available on campus. We\'re working to change that! Thanks for your patience.')

	tool = get_object_or_404(Tool, id=tool_id)
	operator = request.user
	user = get_object_or_404(User, id=user_id)
	project = get_object_or_404(Project, id=project_id)
	staff_charge = staff_charge == 'true'
	response = check_policy_to_enable_tool(tool, operator, user, project, staff_charge)
	if response.status_code != HTTPStatus.OK:
		return response

	# All policy checks passed so enable the tool for the user.
	if tool.interlock and not tool.interlock.unlock():
		raise Exception("The interlock command for this tool failed. The error message returned: " + str(tool.interlock.most_recent_reply))

	# Create a new usage event to track how long the user uses the tool.
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.user = user
	new_usage_event.project = project
	new_usage_event.tool = tool
	new_usage_event.save()

	if staff_charge:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.customer = user
		new_staff_charge.project = project
		new_staff_charge.save()

	return response


@login_required
@require_POST
def disable_tool(request, tool_id):

	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest('Tool control is only available on campus.')

	tool = get_object_or_404(Tool, id=tool_id)
	if tool.get_current_usage_event() is None:
		return HttpResponse()
	downtime = timedelta(minutes=quiet_int(request.POST.get('downtime')))
	response = check_policy_to_disable_tool(tool, request.user, downtime)
	if response.status_code != HTTPStatus.OK:
		return response
	try:
		current_reservation = Reservation.objects.get(start__lt=timezone.now(), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=request.user, tool=tool)
		# Staff are exempt from mandatory reservation shortening when tool usage is complete.
		if request.user.is_staff is False:
			# Shorten the user's reservation to the current time because they're done using the tool.
			new_reservation = deepcopy(current_reservation)
			new_reservation.id = None
			new_reservation.pk = None
			new_reservation.end = timezone.now() + downtime
			new_reservation.save()
			current_reservation.shortened = True
			current_reservation.descendant = new_reservation
			current_reservation.save()
	except Reservation.DoesNotExist:
		pass

	# All policy checks passed so disable the tool for the user.
	if tool.interlock and not tool.interlock.lock():
		error_message = f"The interlock command for the {tool} failed. The error message returned: {tool.interlock.most_recent_reply}"
		logger.error(error_message)
		return HttpResponseServerError(error_message)

	# End the current usage event for the tool
	current_usage_event = tool.get_current_usage_event()
	current_usage_event.end = timezone.now() + downtime

	# Collect post-usage questions
	dynamic_form = DynamicForm(tool.post_usage_questions)
	current_usage_event.run_data = dynamic_form.extract(request)
	dynamic_form.charge_for_consumable(current_usage_event.user, current_usage_event.operator, current_usage_event.project, current_usage_event.run_data)

	current_usage_event.save()
	if request.user.charging_staff_time():
		existing_staff_charge = request.user.get_staff_charge()
		if existing_staff_charge.customer == current_usage_event.user and existing_staff_charge.project == current_usage_event.project:
			response = render(request, 'staff_charges/reminder.html', {'tool': tool})

	return response


@login_required
@require_GET
def past_comments_and_tasks(request):
	try:
		start, end = extract_times(request.GET)
	except:
		return HttpResponseBadRequest('Please enter a start and end date.')
	tool_id = request.GET.get('tool_id')
	try:
		tasks = Task.objects.filter(tool_id=tool_id, creation_time__gt=start, creation_time__lt=end)
		comments = Comment.objects.filter(tool_id=tool_id, creation_date__gt=start, creation_date__lt=end)
	except:
		return HttpResponseBadRequest('Task and comment lookup failed.')
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, 'creation_time', None) or getattr(x, 'creation_date', None))
	past.reverse()
	dictionary = {
		'past': past,
	}
	return render(request, 'tool_control/past_tasks_and_comments.html', dictionary)


@login_required
@require_GET
def ten_most_recent_past_comments_and_tasks(request, tool_id):
	tasks = Task.objects.filter(tool_id=tool_id).order_by('-creation_time')[:10]
	comments = Comment.objects.filter(tool_id=tool_id).order_by('-creation_date')[:10]
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, 'creation_time', None) or getattr(x, 'creation_date', None))
	past.reverse()
	past = past[0:10]
	dictionary = {
		'past': past,
	}
	return render(request, 'tool_control/past_tasks_and_comments.html', dictionary)
