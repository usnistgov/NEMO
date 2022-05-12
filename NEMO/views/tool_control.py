from datetime import datetime, timedelta
from http import HTTPStatus
from itertools import chain
from json import JSONDecodeError, loads
from logging import getLogger
from typing import Dict, List

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template import Context, Template
from django.template.defaultfilters import linebreaksbr
from django.utils import formats, timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from NEMO import rates
from NEMO.decorators import staff_member_required, synchronized
from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.forms import CommentForm, nice_errors
from NEMO.models import (
	AreaAccessRecord,
	Comment,
	Configuration,
	ConfigurationHistory,
	Project,
	Reservation,
	StaffCharge,
	Task,
	TaskCategory,
	TaskStatus,
	Tool,
	ToolUsageCounter,
	UsageEvent,
	User,
)
from NEMO.utilities import (
	BasicDisplayTable,
	EmailCategory,
	export_format_datetime,
	extract_optional_beginning_and_end_times,
	format_datetime,
	quiet_int,
	send_mail,
)
from NEMO.views.calendar import shorten_reservation
from NEMO.views.customization import (
	ApplicationCustomization,
	EmailsCustomization,
	InterlockCustomization,
	get_media_file_contents,
)
from NEMO.views.policy import check_policy_to_disable_tool, check_policy_to_enable_tool
from NEMO.widgets.configuration_editor import ConfigurationEditor
from NEMO.widgets.dynamic_form import DynamicForm, PostUsageQuestion, render_group_questions
from NEMO.widgets.item_tree import ItemTree

tool_control_logger = getLogger(__name__)


@login_required
@require_GET
def tool_control(request, item_type="tool", tool_id=None):
	# item_type is needed for compatibility with 'view_calendar' view on mobile
	""" Presents the tool control view to the user, allowing them to begin/end using a tool or see who else is using it. """
	user: User = request.user
	if user.active_project_count() == 0:
		return render(request, "no_project.html")
	# The tool-choice sidebar is not available for mobile devices, so redirect the user to choose a tool to view.
	if request.device == "mobile" and tool_id is None:
		return redirect("choose_item", next_page="tool_control")
	tools = Tool.objects.filter(visible=True).order_by("_category", "name")
	dictionary = {"tools": tools, "selected_tool": tool_id}
	# The tool-choice sidebar only needs to be rendered for desktop devices, not mobile devices.
	if request.device == "desktop":
		dictionary["rendered_item_tree_html"] = ItemTree().render(None, {"tools": tools, "user": user})
	return render(request, "tool_control/tool_control.html", dictionary)


@login_required
@require_GET
def tool_status(request, tool_id):
	""" Gets the current status of the tool (that is, whether it is currently in use or not). """
	tool = get_object_or_404(Tool, id=tool_id, visible=True)

	dictionary = {
		"tool": tool,
		"tool_rate": rates.rate_class.get_tool_rate(tool),
		"task_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
		"rendered_configuration_html": tool.configuration_widget(request.user),
		"mobile": request.device == "mobile",
		"task_statuses": TaskStatus.objects.all(),
		"post_usage_questions": DynamicForm(tool.post_usage_questions).render("tool_usage_group_question", tool_id),
		"configs": get_tool_full_config_history(tool),
	}

	try:
		current_reservation = Reservation.objects.get(
			start__lt=timezone.now(),
			end__gt=timezone.now(),
			cancelled=False,
			missed=False,
			shortened=False,
			user=request.user,
			tool=tool,
		)
		if request.user == current_reservation.user:
			dictionary["time_left"] = current_reservation.end
	except Reservation.DoesNotExist:
		pass

	# Staff need the user list to be able to qualify users for the tool.
	if request.user.is_staff:
		dictionary["users"] = User.objects.filter(is_active=True)

	return render(request, "tool_control/tool_status.html", dictionary)


@staff_member_required
@require_GET
def use_tool_for_other(request):
	dictionary = {"users": User.objects.filter(is_active=True).exclude(id=request.user.id)}
	return render(request, "tool_control/use_tool_for_other.html", dictionary)


def get_tool_full_config_history(tool: Tool):
	# tool config by user and tool and time
	configs = []
	config_history = ConfigurationHistory.objects.filter(configuration__tool_id=tool.id).order_by("-modification_time")[
					 :20
					 ]
	configurations = tool.current_ordered_configurations()
	for c in config_history:
		for co in configurations:
			if co == c.configuration:
				current_settings = co.current_settings_as_list()
				current_settings[c.slot] = c.setting
				co.current_settings = ", ".join(current_settings)
		config_input = {"configurations": configurations, "render_as_form": False}
		configuration = ConfigurationEditor()
		configs.append(
			{"modification_time": c.modification_time, "user": c.user, "html": configuration.render(None, config_input)}
		)
	return configs


@login_required
@require_POST
def usage_data_history(request, tool_id):
	""" This method return a dictionary of headers and rows containing run_data information for Usage Events """
	csv_export = bool(request.POST.get("csv", False))
	start, end = extract_optional_beginning_and_end_times(request.POST)
	last = request.POST.get("data_history_last")
	user_id = request.POST.get("data_history_user_id")
	show_project_info = request.POST.get("show_project_info")
	if not last and not start and not end:
		# Default to last 25 records
		last = 25
	usage_events = UsageEvent.objects.filter(tool_id=tool_id, end__isnull=False).order_by("-end")
	if start:
		usage_events = usage_events.filter(end__gte=start)
	if end:
		usage_events = usage_events.filter(end__lte=end)
	if user_id:
		try:
			usage_events = usage_events.filter(user_id=int(user_id))
		except ValueError:
			pass
	if last:
		try:
			last = int(last)
		except ValueError:
			last = 25
		usage_events = usage_events[:last]
	table_result = BasicDisplayTable()
	table_result.add_header(("user", "User"))
	if show_project_info:
		table_result.add_header(("project", "Project"))
	table_result.add_header(("date", "Date"))
	for usage_event in usage_events:
		if usage_event.run_data:
			usage_data = {}
			try:
				user_data = f"{usage_event.user.first_name} {usage_event.user.last_name}"
				date_data = format_datetime(usage_event.end, "SHORT_DATETIME_FORMAT")
				run_data: Dict = loads(usage_event.run_data)
				for question_key, question in run_data.items():
					if "user_input" in question:
						if question["type"] == "group":
							for sub_question in question["questions"]:
								table_result.add_header((sub_question["name"], sub_question["title"]))
							for index, user_inputs in question["user_input"].items():
								if index == "0":
									# Special case here the "initial" group of user inputs will go along with the rest of the non-group user inputs
									for name, user_input in user_inputs.items():
										usage_data[name] = user_input
								else:
									# For the other groups of user inputs, we have to add a whole new row
									group_usage_data = {}
									for name, user_input in user_inputs.items():
										group_usage_data[name] = user_input
									if group_usage_data:
										group_usage_data["user"] = user_data
										group_usage_data["date"] = date_data
										if show_project_info:
											group_usage_data["project"] = usage_event.project.name
										table_result.add_row(group_usage_data)
						else:
							table_result.add_header((question_key, question["title"]))
							usage_data[question_key] = question["user_input"]
				if usage_data:
					usage_data["user"] = user_data
					usage_data["date"] = date_data
					if show_project_info:
						usage_data["project"] = usage_event.project.name
					table_result.add_row(usage_data)
			except JSONDecodeError:
				tool_control_logger.debug("error decoding run_data: " + usage_event.run_data)
	if csv_export:
		response = table_result.to_csv()
		filename = f"tool_usage_data_export_{export_format_datetime()}.csv"
		response["Content-Disposition"] = f'attachment; filename="{filename}"'
		return response
	else:
		dictionary = {
			"tool_id": tool_id,
			"data_history_start": start.date() if start else None,
			"data_history_end": end.date() if end else None,
			"data_history_last": str(last),
			"usage_data_table": table_result,
			"data_history_user": User.objects.get(id=user_id) if user_id else None,
			"show_project_info": show_project_info or False,
			"users": User.objects.filter(is_active=True)
		}
		return render(request, "tool_control/usage_data.html", dictionary)


@login_required
@require_POST
def tool_configuration(request):
	""" Sets the current configuration of a tool. """
	try:
		configuration = Configuration.objects.get(id=request.POST["configuration_id"])
	except:
		return HttpResponseNotFound("Configuration not found.")
	if not configuration.enabled:
		return HttpResponseBadRequest("This configuration is not enabled")
	if configuration.tool.in_use():
		return HttpResponseBadRequest("Cannot change a configuration while a tool is in use.")
	if not configuration.user_is_maintainer(request.user):
		return HttpResponseBadRequest("You are not authorized to change this configuration.")
	try:
		slot = int(request.POST["slot"])
		choice = int(request.POST["choice"])
	except:
		return HttpResponseBadRequest("Invalid configuration parameters.")
	try:
		configuration.replace_current_setting(slot, choice)
	except IndexError:
		return HttpResponseBadRequest("Invalid configuration choice.")
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
	comment.expiration_date = (
		None
		if form.cleaned_data["expiration"] == 0
		else timezone.now() + timedelta(days=form.cleaned_data["expiration"])
	)
	comment.save()
	return redirect("tool_control")


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
	return redirect("tool_control")


def determine_tool_status(tool):
	# Make the tool operational when all problems are resolved that require a shutdown.
	if tool.task_set.filter(force_shutdown=True, cancelled=False, resolved=False).count() == 0:
		tool.operational = True
	else:
		tool.operational = False
	tool.save()


@login_required
@require_POST
@synchronized('tool_id')
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
	""" Enable a tool for a user. The user must be qualified to do so based on the lab usage policy. """

	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest(
			"Tool control is only available on campus. We're working to change that! Thanks for your patience."
		)

	tool = get_object_or_404(Tool, id=tool_id)
	operator = request.user
	user = get_object_or_404(User, id=user_id)
	project = get_object_or_404(Project, id=project_id)
	staff_charge = staff_charge == "true"
	bypass_interlock = request.POST.get("bypass", 'False') == 'True'
	response = check_policy_to_enable_tool(tool, operator, user, project, staff_charge)
	if response.status_code != HTTPStatus.OK:
		return response

	# All policy checks passed so enable the tool for the user.
	if tool.interlock and not tool.interlock.unlock():
		if bypass_interlock and interlock_bypass_allowed(user):
			pass
		else:
			return interlock_error("Enable", user)

	# Start staff charge before tool usage
	if staff_charge:
		new_staff_charge = StaffCharge()
		new_staff_charge.staff_member = request.user
		new_staff_charge.customer = user
		new_staff_charge.project = project
		new_staff_charge.save()
		# If the tool requires area access, start charging area access time
		if tool.requires_area_access:
			area_access = AreaAccessRecord()
			area_access.area = tool.requires_area_access
			area_access.staff_charge = new_staff_charge
			area_access.customer = new_staff_charge.customer
			area_access.project = new_staff_charge.project
			area_access.save()

	# Create a new usage event to track how long the user uses the tool.
	new_usage_event = UsageEvent()
	new_usage_event.operator = operator
	new_usage_event.user = user
	new_usage_event.project = project
	new_usage_event.tool = tool
	new_usage_event.save()

	return response


@login_required
@require_POST
@synchronized('tool_id')
def disable_tool(request, tool_id):
	if not settings.ALLOW_CONDITIONAL_URLS:
		return HttpResponseBadRequest("Tool control is only available on campus.")

	tool = get_object_or_404(Tool, id=tool_id)
	if tool.get_current_usage_event() is None:
		return HttpResponse()
	downtime = timedelta(minutes=quiet_int(request.POST.get("downtime")))
	bypass_interlock = request.POST.get("bypass", 'False') == 'True'
	response = check_policy_to_disable_tool(tool, request.user, downtime)
	if response.status_code != HTTPStatus.OK:
		return response

	# All policy checks passed so disable the tool for the user.
	if tool.interlock and not tool.interlock.lock():
		if bypass_interlock and interlock_bypass_allowed(request.user):
			pass
		else:
			return interlock_error("Disable", request.user)

	# Shorten the user's tool reservation since we are now done using the tool
	shorten_reservation(user=request.user, item=tool, new_end=timezone.now() + downtime)

	# End the current usage event for the tool
	current_usage_event = tool.get_current_usage_event()
	current_usage_event.end = timezone.now() + downtime

	# Collect post-usage questions
	dynamic_form = DynamicForm(tool.post_usage_questions)

	try:
		current_usage_event.run_data = dynamic_form.extract(request)
	except RequiredUnansweredQuestionsException as e:
		if request.user.is_staff and request.user != current_usage_event.operator and current_usage_event.user != request.user:
			# if a staff is forcing somebody off the tool and there are required questions, send an email and proceed
			current_usage_event.run_data = e.run_data
			email_managers_required_questions_disable_tool(current_usage_event.operator, request.user, tool, e.questions)
		else:
			return HttpResponseBadRequest(str(e))

	dynamic_form.charge_for_consumables(
		current_usage_event.user,
		current_usage_event.operator,
		current_usage_event.project,
		current_usage_event.run_data,
		request
	)
	dynamic_form.update_tool_counters(current_usage_event.run_data, tool.id)

	current_usage_event.save()
	user: User = request.user
	if user.charging_staff_time():
		existing_staff_charge = user.get_staff_charge()
		if (
				existing_staff_charge.customer == current_usage_event.user
				and existing_staff_charge.project == current_usage_event.project
		):
			response = render(request, "staff_charges/reminder.html", {"tool": tool})

	return response


@login_required
@require_GET
def past_comments_and_tasks(request):
	start, end = extract_optional_beginning_and_end_times(request.GET)
	search = request.GET.get("search")
	if not start and not end and not search:
		return HttpResponseBadRequest("Please enter a search keyword, start date or end date.")
	tool_id = request.GET.get("tool_id")
	try:
		tasks = Task.objects.filter(tool_id=tool_id)
		comments = Comment.objects.filter(tool_id=tool_id, staff_only=False)
		if start:
			tasks = tasks.filter(creation_time__gt=start)
			comments = comments.filter(creation_date__gt=start)
		if end:
			tasks = tasks.filter(creation_time__lt=end)
			comments = comments.filter(creation_date__lt=end)
		if search:
			tasks = tasks.filter(problem_description__icontains=search)
			comments = comments.filter(content__icontains=search)
	except:
		return HttpResponseBadRequest("Task and comment lookup failed.")
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, "creation_time", None) or getattr(x, "creation_date", None))
	past.reverse()
	if request.GET.get("export"):
		return export_comments_and_tasks_to_text(past)
	return render(request, "tool_control/past_tasks_and_comments.html", {"past": past})


@login_required
@require_GET
def ten_most_recent_past_comments_and_tasks(request, tool_id):
	tasks = Task.objects.filter(tool_id=tool_id).order_by("-creation_time")[:10]
	comments = Comment.objects.filter(tool_id=tool_id, staff_only=False).order_by("-creation_date")[:10]
	past = list(chain(tasks, comments))
	past.sort(key=lambda x: getattr(x, "creation_time", None) or getattr(x, "creation_date", None))
	past.reverse()
	past = past[0:10]
	if request.GET.get("export"):
		return export_comments_and_tasks_to_text(past)
	return render(request, "tool_control/past_tasks_and_comments.html", {"past": past})


def export_comments_and_tasks_to_text(comments_and_tasks: List):
	content = "No tasks or comments were created between these dates." if not comments_and_tasks else ""
	for item in comments_and_tasks:
		if isinstance(item, Comment):
			comment: Comment = item
			staff_only = "staff only " if comment.staff_only else ""
			content += f"On {format_datetime(comment.creation_date)} {comment.author} wrote this {staff_only}comment:\n"
			content += f"{comment.content}\n"
			if comment.hide_date:
				content += f"{comment.hidden_by} hid the comment on {format_datetime(comment.hide_date)}.\n"
		elif isinstance(item, Task):
			task: Task = item
			content += f"On {format_datetime(task.creation_time)} {task.creator} created this task:\n"
			if task.problem_category:
				content += f"{task.problem_category.name}\n"
			if task.force_shutdown:
				content += "\nThe tool was shut down because of this task.\n"
			if task.progress_description:
				content += f"\n{task.progress_description}\n"
			if task.resolved:
				resolution_category = f"({task.resolution_category}) " if task.resolution_category else ""
				content += f"\nResolved {resolution_category}On {format_datetime(task.resolution_time)} by {task.resolver }.\n"
				if task.resolution_description:
					content += f"{task.resolution_description}\n"
			elif task.cancelled:
				content += f"\nCancelled On {format_datetime(task.resolution_time)} by {task.resolver}.\n"
		content += "\n---------------------------------------------------\n\n"
	response = HttpResponse(content, content_type='text/plain')
	response['Content-Disposition'] = 'attachment; filename={0}'.format(f"comments_and_tasks_export_{export_format_datetime()}.txt")
	return response


@login_required
@require_GET
def tool_usage_group_question(request, tool_id, group_name):
	tool = get_object_or_404(Tool, id=tool_id)
	return HttpResponse(render_group_questions(request, tool.post_usage_questions, "tool_usage_group_question", tool_id, group_name))


@staff_member_required
@require_GET
def reset_tool_counter(request, counter_id):
	counter = get_object_or_404(ToolUsageCounter, id=counter_id)
	counter.last_reset_value = counter.value
	counter.value = 0
	counter.last_reset = datetime.now()
	counter.last_reset_by = request.user
	counter.save()

	# Save a comment about the counter being reset.
	comment = Comment()
	comment.tool = counter.tool
	comment.content = f"The {counter.name} counter was reset to 0. Its last value was {counter.last_reset_value}."
	comment.author = request.user
	comment.expiration_date = datetime.now() + timedelta(weeks=1)
	comment.save()

	# Send an email to Lab Managers about the counter being reset.
	facility_managers = User.objects.filter(is_active=True, is_facility_manager=True).values_list('email', flat=True)
	if facility_managers:
		message = f"""The {counter.name} counter for the {counter.tool.name} was reset to 0 on {formats.localize(counter.last_reset)} by {counter.last_reset_by}.
	
Its last value was {counter.last_reset_value}."""
		send_mail(
			subject=f"{counter.tool.name} counter reset",
			content=message,
			from_email=settings.SERVER_EMAIL,
			to=facility_managers,
			email_category=EmailCategory.SYSTEM,
		)
	return redirect("tool_control")


def interlock_bypass_allowed(user: User):
	return user.is_staff or InterlockCustomization.get('allow_bypass_interlock_on_failure') == 'enabled'


def interlock_error(action:str, user:User):
	error_message = InterlockCustomization.get('tool_interlock_failure_message')
	dictionary = {
		"message": linebreaksbr(error_message),
		"bypass_allowed": interlock_bypass_allowed(user),
		"action": action
	}
	return JsonResponse(dictionary, status=501)


def email_managers_required_questions_disable_tool(tool_user:User, staff_member:User, tool:Tool, questions:List[PostUsageQuestion]):
	abuse_email_address = EmailsCustomization.get('abuse_email_address')
	facility_managers = User.objects.filter(is_active=True, is_facility_manager=True).values_list('email', flat=True)
	facility_name = ApplicationCustomization.get('facility_name')
	ccs = set(tuple([r for r in [staff_member.email, tool.primary_owner.email, *tool.backup_owners.all().values_list('email', flat=True), *facility_managers] if r]))
	display_questions = "".join([linebreaksbr(mark_safe(question.render_as_text())) + "<br/><br/>" for question in questions])
	message = f"""
Dear {tool_user.get_name()},<br/>
You have been logged off by staff from the {tool} that requires answers to the following post-usage questions:<br/>
<br/>
{display_questions}
<br/>
Regards,<br/>
<br/>
{facility_name} Management<br/>
"""
	send_mail(subject=f"Unanswered post‑usage questions after logoff from the {tool.name}", content=message, from_email=abuse_email_address, to=[tool_user.email], cc=ccs, email_category=EmailCategory.ABUSE)


def send_tool_usage_counter_email(counter: ToolUsageCounter):
	user_office_email = EmailsCustomization.get('user_office_email_address')
	message = get_media_file_contents('counter_threshold_reached_email.html')
	if user_office_email and message:
		subject = f"Warning threshold reached for {counter.tool.name} {counter.name} counter"
		rendered_message = Template(message).render(Context({'counter': counter}))
		send_mail(subject=subject, content=rendered_message, from_email=user_office_email, to=counter.warning_email, email_category=EmailCategory.SYSTEM)