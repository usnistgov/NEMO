from datetime import datetime, timedelta
from http import HTTPStatus
from itertools import chain
from json import JSONDecodeError, loads
from logging import getLogger
from typing import Dict, List

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import linebreaksbr
from django.utils import formats, timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import staff_member_required, synchronized
from NEMO.exceptions import ProjectChargeException, RequiredUnansweredQuestionsException
from NEMO.forms import CommentForm, nice_errors
from NEMO.models import (
    AreaAccessRecord,
    Comment,
    Configuration,
    ConfigurationHistory,
    EmailNotificationType,
    Project,
    Reservation,
    StaffCharge,
    Task,
    TaskCategory,
    TaskStatus,
    Tool,
    ToolUsageCounter,
    ToolWaitList,
    UsageEvent,
    User,
)
from NEMO.policy import policy_class as policy
from NEMO.utilities import (
    BasicDisplayTable,
    EmailCategory,
    export_format_datetime,
    extract_optional_beginning_and_end_times,
    format_datetime,
    get_email_from_settings,
    quiet_int,
    render_email_template,
    send_mail,
)
from NEMO.views.area_access import able_to_self_log_out_of_area
from NEMO.views.calendar import shorten_reservation
from NEMO.views.customization import (
    CalendarCustomization,
    EmailsCustomization,
    InterlockCustomization,
    RemoteWorkCustomization,
    ToolCustomization,
    get_media_file_contents,
)
from NEMO.widgets.configuration_editor import ConfigurationEditor
from NEMO.widgets.dynamic_form import DynamicForm, PostUsageQuestion, render_group_questions
from NEMO.widgets.item_tree import ItemTree

tool_control_logger = getLogger(__name__)


@login_required
@require_GET
def tool_control(request, item_type="tool", tool_id=None):
    # item_type is needed for compatibility with 'view_calendar' view on mobile
    """Presents the tool control view to the user, allowing them to begin/end using a tool or see who else is using it."""
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
    dictionary["calendar_qualified_tools"] = CalendarCustomization.get("calendar_qualified_tools")
    return render(request, "tool_control/tool_control.html", dictionary)


@login_required
@require_GET
def tool_status(request, tool_id):
    """Gets the current status of the tool (that is, whether it is currently in use or not)."""
    from NEMO.rates import rate_class

    user: User = request.user
    tool = get_object_or_404(Tool, id=tool_id, visible=True)
    user_is_qualified = tool.user_set.filter(id=user.id).exists()
    broadcast_upcoming_reservation = ToolCustomization.get("tool_control_broadcast_upcoming_reservation")
    wait_list = tool.current_wait_list()
    user_wait_list_entry = wait_list.filter(user=request.user).first()
    user_wait_list_position = (
        (
            ToolWaitList.objects.filter(
                tool=tool, date_entered__lte=user_wait_list_entry.date_entered, expired=False, deleted=False
            )
            .exclude(user=user)
            .count()
            + 1
        )
        if user_wait_list_entry
        else 0
    )
    tool_credentials = []
    if ToolCustomization.get_bool("tool_control_show_tool_credentials") and (user.is_staff or user.is_facility_manager):
        if user.is_facility_manager:
            tool_credentials = tool.toolcredentials_set.all()
        else:
            tool_credentials = tool.toolcredentials_set.filter(
                Q(authorized_staff__isnull=True) | Q(authorized_staff__in=[user])
            )
    dictionary = {
        "tool": tool,
        "tool_credentials": tool_credentials,
        "tool_rate": rate_class.get_tool_rate(tool, user),
        "task_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
        "rendered_configuration_html": tool.configuration_widget(user),
        "mobile": request.device == "mobile",
        "task_statuses": TaskStatus.objects.all(),
        "pre_usage_questions": DynamicForm(tool.pre_usage_questions).render("tool_usage_group_question", tool_id),
        "post_usage_questions": DynamicForm(tool.post_usage_questions).render("tool_usage_group_question", tool_id),
        "show_broadcast_upcoming_reservation": user.is_any_part_of_staff
        or (user_is_qualified and broadcast_upcoming_reservation == "qualified")
        or broadcast_upcoming_reservation == "all",
        "tool_control_show_task_details": ToolCustomization.get_bool("tool_control_show_task_details"),
        "has_usage_questions": True if tool.pre_usage_questions or tool.post_usage_questions else False,
        "user_can_see_documents": user.is_any_part_of_staff
        or not ToolCustomization.get_bool("tool_control_show_documents_only_qualified_users")
        or user_is_qualified,
        "wait_list_position": user_wait_list_position,  # 0 if not in wait list
        "wait_list": wait_list,
        "show_wait_list": (
            tool.allow_wait_list()
            and (
                not (
                    tool.get_current_usage_event().operator.id == user.id
                    or tool.get_current_usage_event().user.id == user.id
                )
                if tool.in_use()
                else wait_list.count() > 0
            )
        ),
    }

    try:
        current_reservation = Reservation.objects.get(
            start__lt=timezone.now(),
            end__gt=timezone.now(),
            cancelled=False,
            missed=False,
            shortened=False,
            user=user,
            tool=tool,
        )
        if user == current_reservation.user:
            dictionary["time_left"] = current_reservation.end
    except Reservation.DoesNotExist:
        pass

    # Staff need the user list to be able to qualify users for the tool.
    if user.is_staff:
        dictionary["users"] = User.objects.filter(is_active=True)

    return render(request, "tool_control/tool_status.html", dictionary)


@staff_member_required
@require_GET
def use_tool_for_other(request):
    dictionary = {"users": User.objects.filter(is_active=True).exclude(id=request.user.id)}
    return render(request, "tool_control/use_tool_for_other.html", dictionary)


@login_required
@require_GET
def tool_config_history(request, tool_id):
    # tool config by user and tool and time
    configs = []
    config_history = ConfigurationHistory.objects.filter(configuration__tool_id=tool_id).order_by("-modification_time")[
        :20
    ]
    for history in config_history:
        configuration = ConfigurationEditor()
        conf = history.configuration
        conf.name = history.item_name
        conf.current_settings = history.setting
        configs.append(
            {
                "modification_time": history.modification_time,
                "configuration": history.configuration,
                "user": history.user,
                "html": mark_safe(configuration._render_for_one(conf, render_as_form=False)),
            }
        )
    return render(request, "tool_control/config_history.html", {"configs": configs})


@login_required
@require_POST
def usage_data_history(request, tool_id):
    """This method return a dictionary of headers and rows containing run_data information for Usage Events"""
    csv_export = request.POST.get("csv")
    start, end = extract_optional_beginning_and_end_times(request.POST)
    last = request.POST.get("data_history_last")
    user_id = request.POST.get("data_history_user_id")
    show_project_info = request.POST.get("show_project_info")

    if not last and not start and not end:
        # Default to last 25 records
        last = 25
    usage_events = UsageEvent.objects.filter(tool_id=tool_id)

    if start:
        usage_events = usage_events.filter(end__gte=start)
    if end:
        usage_events = usage_events.filter(end__lte=end)
    if user_id:
        try:
            usage_events = usage_events.filter(user_id=int(user_id))
        except ValueError:
            pass

    pre_usage_events = usage_events.order_by("-start")
    post_usage_events = usage_events.filter(end__isnull=False).order_by("-end")
    if last:
        try:
            last = int(last)
        except ValueError:
            last = 25
        pre_usage_events = pre_usage_events[:last]
        post_usage_events = post_usage_events[:last]

    table_pre_run_data = BasicDisplayTable()
    table_pre_run_data.add_header(("user", "User"))
    if show_project_info:
        table_pre_run_data.add_header(("project", "Project"))
    table_pre_run_data.add_header(("date", "Start date"))

    table_run_data = BasicDisplayTable()
    table_run_data.add_header(("user", "User"))
    if show_project_info:
        table_run_data.add_header(("project", "Project"))
    table_run_data.add_header(("date", "End date"))

    for usage_event in pre_usage_events:
        if usage_event.pre_run_data:
            format_usage_data(
                table_pre_run_data, usage_event, usage_event.pre_run_data, usage_event.start, show_project_info
            )

    for usage_event in post_usage_events:
        if usage_event.run_data:
            format_usage_data(table_run_data, usage_event, usage_event.run_data, usage_event.end, show_project_info)

    if csv_export:
        response = table_run_data.to_csv() if csv_export == "run" else table_pre_run_data.to_csv()
        filename = f"tool{'' if csv_export == 'run' else '_pre'}_usage_data_export_{export_format_datetime()}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    else:
        dictionary = {
            "tool_id": tool_id,
            "data_history_start": start.date() if start else None,
            "data_history_end": end.date() if end else None,
            "data_history_last": str(last),
            "run_data_table": table_run_data,
            "pre_run_data_table": table_pre_run_data,
            "data_history_user": User.objects.get(id=user_id) if user_id else None,
            "show_project_info": show_project_info or False,
            "users": User.objects.all(),
        }
        return render(request, "tool_control/usage_data.html", dictionary)


@login_required
@require_POST
def tool_configuration(request):
    """Sets the current configuration of a tool."""
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
    history.item_name = configuration.configurable_item_name or configuration.name
    if len(configuration.range_of_configurable_items()) > 1:
        history.item_name += f" #{slot + 1}"
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
    save_comment(request.user, form)

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


def save_comment(user, form):
    comment = form.save(commit=False)
    comment.content = comment.content.strip()
    comment.author = user
    comment.expiration_date = (
        None
        if form.cleaned_data["expiration"] == -1
        else timezone.now() + timedelta(days=form.cleaned_data["expiration"])
    )
    comment.save()


def determine_tool_status(tool):
    # Make the tool operational when all problems are resolved that require a shutdown.
    if tool.task_set.filter(force_shutdown=True, cancelled=False, resolved=False).count() == 0:
        tool.operational = True
    else:
        tool.operational = False
    tool.save()


@login_required
@require_POST
@synchronized("tool_id")
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
    """Enable a tool for a user. The user must be qualified to do so based on the lab usage policy."""

    if not settings.ALLOW_CONDITIONAL_URLS:
        return HttpResponseBadRequest(
            "Tool control is only available on campus. We're working to change that! Thanks for your patience."
        )

    tool = get_object_or_404(Tool, id=tool_id)
    operator = request.user
    user = get_object_or_404(User, id=user_id)
    project = get_object_or_404(Project, id=project_id)
    staff_charge = staff_charge == "true"
    bypass_interlock = request.POST.get("bypass", "False") == "True"
    # Figure out if the tool usage is part of remote work
    # 1: Staff charge means it's always remote work
    # 2: Always remote if operator is different from the user
    # 3: Unless customization is set to ask explicitly
    remote_work = user != operator and operator.is_staff
    if RemoteWorkCustomization.get_bool("remote_work_ask_explicitly"):
        remote_work = remote_work and bool(request.POST.get("remote_work", False))
    response = policy.check_to_enable_tool(tool, operator, user, project, staff_charge, remote_work)
    if response.status_code != HTTPStatus.OK:
        return response

    # Create a new usage event to track how long the user uses the tool.
    new_usage_event = UsageEvent()
    new_usage_event.operator = operator
    new_usage_event.user = user
    new_usage_event.project = project
    new_usage_event.tool = tool

    # Collect pre-usage questions and validate them
    dynamic_form = DynamicForm(tool.pre_usage_questions)

    try:
        new_usage_event.pre_run_data = dynamic_form.extract(request)
    except RequiredUnansweredQuestionsException as e:
        return HttpResponseBadRequest(str(e))

    # All policy checks passed so enable the tool for the user.
    if tool.interlock and not tool.interlock.unlock():
        if bypass_interlock and interlock_bypass_allowed(user):
            pass
        else:
            return interlock_error("Enable", user)

    # Start staff charge before tool usage
    if staff_charge:
        # Staff charge means always a remote
        remote_work = True
        new_staff_charge = StaffCharge()
        new_staff_charge.staff_member = request.user
        new_staff_charge.customer = user
        new_staff_charge.project = project
        try:
            # Check that staff charge is actually allowed
            policy.check_billing_to_project(project, user, new_staff_charge, new_staff_charge)
        except ProjectChargeException as e:
            return HttpResponseBadRequest(e.msg)
        new_staff_charge.save()
        # If the tool requires area access, start charging area access time
        if tool.requires_area_access and RemoteWorkCustomization.get_bool(
            "remote_work_start_area_access_automatically"
        ):
            area_access = AreaAccessRecord()
            area_access.area = tool.requires_area_access
            area_access.staff_charge = new_staff_charge
            area_access.customer = new_staff_charge.customer
            area_access.project = new_staff_charge.project
            area_access.save()

    # Now we can safely save the usage event
    new_usage_event.remote_work = remote_work
    new_usage_event.save()

    # Remove wait list entry if it exists
    wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=user)
    if wait_list_entry.count() > 0:
        wait_list_entry.update(deleted=True, date_exited=timezone.now())

    try:
        dynamic_form.charge_for_consumables(new_usage_event, new_usage_event.pre_run_data, request)
    except Exception as e:
        return HttpResponseBadRequest(str(e))
    dynamic_form.update_tool_counters(new_usage_event.pre_run_data, tool.id)

    return response


@login_required
@require_POST
@synchronized("tool_id")
def disable_tool(request, tool_id):
    if not settings.ALLOW_CONDITIONAL_URLS:
        return HttpResponseBadRequest("Tool control is only available on campus.")

    tool = get_object_or_404(Tool, id=tool_id)
    if tool.get_current_usage_event() is None:
        return HttpResponse()
    user: User = request.user
    downtime = timedelta(minutes=quiet_int(request.POST.get("downtime")))
    bypass_interlock = request.POST.get("bypass", "False") == "True"
    response = policy.check_to_disable_tool(tool, user, downtime)
    if response.status_code != HTTPStatus.OK:
        return response

    # All policy checks passed so disable the tool for the user.
    if tool.interlock and not tool.interlock.lock():
        if bypass_interlock and interlock_bypass_allowed(user):
            pass
        else:
            return interlock_error("Disable", user)

    # Shorten the user's tool reservation since we are now done using the tool
    current_usage_event = tool.get_current_usage_event()
    staff_shortening = request.POST.get("shorten", False)
    shorten_reservation(
        user=current_usage_event.user, item=tool, new_end=timezone.now() + downtime, force=staff_shortening
    )

    # End the current usage event for the tool
    current_usage_event.end = timezone.now() + downtime

    # Collect post-usage questions
    dynamic_form = DynamicForm(tool.post_usage_questions)

    try:
        current_usage_event.run_data = dynamic_form.extract(request)
    except RequiredUnansweredQuestionsException as e:
        if (
            (user.is_staff or user.is_user_office)
            and user != current_usage_event.operator
            and current_usage_event.user != user
        ):
            # if a staff is forcing somebody off the tool and there are required questions, send an email and proceed
            current_usage_event.run_data = e.run_data
            email_managers_required_questions_disable_tool(current_usage_event.operator, user, tool, e.questions)
        else:
            return HttpResponseBadRequest(str(e))

    try:
        dynamic_form.charge_for_consumables(current_usage_event, current_usage_event.run_data, request)
    except Exception as e:
        return HttpResponseBadRequest(str(e))
    dynamic_form.update_tool_counters(current_usage_event.run_data, tool.id)

    current_usage_event.save()
    if user.charging_staff_time():
        existing_staff_charge = user.get_staff_charge()
        if (
            existing_staff_charge.customer == current_usage_event.user
            and existing_staff_charge.project == current_usage_event.project
        ):
            return render(request, "staff_charges/reminder.html", {"tool": tool})

    area_record = user.area_access_record()
    if area_record and tool.ask_to_leave_area_when_done_using and able_to_self_log_out_of_area(user):
        return render(request, "tool_control/logout_user.html", {"area": area_record.area, "tool": tool})

    return HttpResponse()


@login_required
@require_POST
def enter_wait_list(request):
    tool = get_object_or_404(Tool, id=request.POST["tool_id"])

    if not tool.allow_wait_list():
        return HttpResponseBadRequest("This tool does not operate in wait list mode.")

    user = request.user
    wait_list_other_users = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False).exclude(user=user)
    wait_list_user_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=user)

    # User must not be in the wait list
    if wait_list_user_entry.count() > 0:
        return HttpResponseBadRequest("You are already in the wait list.")

    # The tool must be in use or have a wait list
    current_usage_event = tool.get_current_usage_event()
    if not current_usage_event and wait_list_other_users.count() == 0:
        return HttpResponseBadRequest("The tool is free to use.")

    # The user must be qualified to use the tool itself, or the parent tool in case of alternate tool.
    tool_to_check_qualifications = tool.parent_tool if tool.is_child_tool() else tool
    if tool_to_check_qualifications not in user.qualifications.all() and not user.is_staff:
        return HttpResponseBadRequest("You are not qualified to use this tool.")

    entry = ToolWaitList()
    entry.user = user
    entry.tool = tool
    entry.save()

    return HttpResponse()


@login_required
@require_POST
def exit_wait_list(request):
    tool = get_object_or_404(Tool, id=request.POST["tool_id"])
    user = request.user
    wait_list_entry = ToolWaitList.objects.filter(tool=tool, expired=False, deleted=False, user=user)
    if wait_list_entry.count() == 0:
        return HttpResponseBadRequest("You are not in the wait list.")
    do_exit_wait_list(wait_list_entry, timezone.now())
    return HttpResponse()


def do_exit_wait_list(entry, time):
    entry.update(deleted=True, date_exited=time)


@login_required
@require_GET
def past_comments_and_tasks(request):
    try:
        user: User = request.user
        start, end = extract_optional_beginning_and_end_times(request.GET)
        search = request.GET.get("search")
        if not start and not end and not search:
            return HttpResponseBadRequest("Please enter a search keyword, start date or end date.")
        tool_id = request.GET.get("tool_id")
        tasks = Task.objects.filter(tool_id=tool_id)
        comments = Comment.objects.filter(tool_id=tool_id)
        if not user.is_staff:
            comments = comments.filter(staff_only=False)
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
    user: User = request.user
    tasks = Task.objects.filter(tool_id=tool_id).order_by("-creation_time")[:10]
    comments = Comment.objects.filter(tool_id=tool_id).order_by("-creation_date")
    if not user.is_staff:
        comments = comments.filter(staff_only=False)
    comments = comments[:10]
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
                content += (
                    f"\nResolved {resolution_category}On {format_datetime(task.resolution_time)} by {task.resolver }.\n"
                )
                if task.resolution_description:
                    content += f"{task.resolution_description}\n"
            elif task.cancelled:
                content += f"\nCancelled On {format_datetime(task.resolution_time)} by {task.resolver}.\n"
        content += "\n---------------------------------------------------\n\n"
    response = HttpResponse(content, content_type="text/plain")
    response["Content-Disposition"] = "attachment; filename={0}".format(
        f"comments_and_tasks_export_{export_format_datetime()}.txt"
    )
    return response


@login_required
@require_GET
def tool_usage_group_question(request, tool_id, group_name):
    tool = get_object_or_404(Tool, id=tool_id)
    return HttpResponse(
        render_group_questions(request, tool.post_usage_questions, "tool_usage_group_question", tool_id, group_name)
    )


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
    comment.expiration_date = timezone.now()
    comment.save()

    # Email Lab Managers about the counter being reset.
    facility_managers = [
        email
        for manager in User.objects.filter(is_active=True, is_facility_manager=True)
        for email in manager.get_emails(manager.get_preferences().email_send_task_updates)
    ]
    if facility_managers:
        message = f"""The {counter.name} counter for the {counter.tool.name} was reset to 0 on {formats.localize(counter.last_reset)} by {counter.last_reset_by}.
	
Its last value was {counter.last_reset_value}."""
        send_mail(
            subject=f"{counter.tool.name} counter reset",
            content=message,
            from_email=get_email_from_settings(),
            to=facility_managers,
            email_category=EmailCategory.SYSTEM,
        )
    return redirect("tool_control")


def interlock_bypass_allowed(user: User):
    return user.is_staff or InterlockCustomization.get_bool("allow_bypass_interlock_on_failure")


def interlock_error(action: str, user: User):
    error_message = InterlockCustomization.get("tool_interlock_failure_message")
    dictionary = {
        "message": linebreaksbr(error_message),
        "bypass_allowed": interlock_bypass_allowed(user),
        "action": action,
    }
    return JsonResponse(dictionary, status=501)


def email_managers_required_questions_disable_tool(
    tool_user: User, staff_member: User, tool: Tool, questions: List[PostUsageQuestion]
):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    abuse_email_address = EmailsCustomization.get("abuse_email_address")
    message = get_media_file_contents("tool_required_unanswered_questions_email.html")
    if message:
        cc_users: List[User] = [staff_member, tool.primary_owner]
        # Add facility managers as CC based on their tool notification preferences if any
        cc_users.extend(
            User.objects.filter(is_active=True, is_facility_manager=True).filter(
                Q(preferences__tool_task_notifications__isnull=True)
                | Q(preferences__tool_task_notifications__in=[tool])
            )
        )
        ccs = [email for user in cc_users for email in user.get_emails(EmailNotificationType.BOTH_EMAILS)]
        ccs.append(abuse_email_address)
        rendered_message = render_email_template(message, {"user": tool_user, "tool": tool, "questions": questions})
        tos = tool_user.get_emails(EmailNotificationType.BOTH_EMAILS)
        send_mail(
            subject=f"Unanswered post‑usage questions after logoff from the {tool.name}",
            content=rendered_message,
            from_email=user_office_email,
            to=tos,
            cc=ccs,
            email_category=EmailCategory.ABUSE,
        )


def send_tool_usage_counter_email(counter: ToolUsageCounter):
    user_office_email = EmailsCustomization.get("user_office_email_address")
    message = get_media_file_contents("counter_threshold_reached_email.html")
    if user_office_email and message:
        subject = f"Warning threshold reached for {counter.tool.name} {counter.name} counter"
        rendered_message = render_email_template(message, {"counter": counter})
        send_mail(
            subject=subject,
            content=rendered_message,
            from_email=user_office_email,
            to=counter.warning_email,
            email_category=EmailCategory.SYSTEM,
        )


def format_usage_data(
    table_result: BasicDisplayTable,
    usage_event: UsageEvent,
    usage_run_data: str,
    date_field: datetime,
    show_project_info: str,
):
    usage_data = {}
    date_data = format_datetime(date_field, "SHORT_DATETIME_FORMAT")

    try:
        user_data = f"{usage_event.user.first_name} {usage_event.user.last_name}"
        run_data: Dict = loads(usage_run_data)
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
        tool_control_logger.debug("error decoding run_data: " + usage_run_data)
