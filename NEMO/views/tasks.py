from logging import getLogger
from typing import List, Set

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import linebreaksbr
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import staff_member_required
from NEMO.forms import TaskForm, TaskImagesForm, nice_errors
from NEMO.models import (
    Interlock,
    Reservation,
    SafetyIssue,
    Task,
    TaskCategory,
    TaskHistory,
    TaskImages,
    TaskStatus,
    UsageEvent,
    User,
)
from NEMO.utilities import (
    EmailCategory,
    as_timezone,
    bootstrap_primary_color,
    create_email_attachment,
    format_datetime,
    get_full_url,
    render_email_template,
    resize_image,
    send_mail,
)
from NEMO.views.customization import (
    ApplicationCustomization,
    EmailsCustomization,
    ToolCustomization,
    get_media_file_contents,
)
from NEMO.views.safety import send_safety_email_notification
from NEMO.views.tool_control import determine_tool_status

tasks_logger = getLogger("NEMO.Tasks")


@login_required
@require_POST
def create(request):
    """
    This could be a problem report or shutdown notification.
    """
    user: User = request.user
    images_form = TaskImagesForm(request.POST, request.FILES)
    form = TaskForm(user, data=request.POST)
    if not form.is_valid() or not images_form.is_valid():
        errors = nice_errors(form)
        errors.update(nice_errors(images_form))
        dictionary = {
            "title": "Task creation failed",
            "heading": "Something went wrong while reporting the problem",
            "content": errors.as_ul(),
        }
        return render(request, "acknowledgement.html", dictionary)

    if not settings.ALLOW_CONDITIONAL_URLS and form.cleaned_data["force_shutdown"]:
        site_title = ApplicationCustomization.get("site_title")

        dictionary = {
            "title": "Task creation failed",
            "heading": "Something went wrong while reporting the problem",
            "content": f"Tool control is only available on campus. When creating a task, you can't force a tool shutdown while using {site_title} off campus.",
        }
        return render(request, "acknowledgement.html", dictionary)

    task = form.save()
    task_images = save_task_images(request, task)

    save_task(request, task, user, task_images)

    return redirect("tool_control")


def save_task(request, task: Task, user: User, task_images: List[TaskImages] = None):
    task.save()

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
        concern = (
            "This safety issue was automatically created because a "
            + str(task.tool).lower()
            + " problem was identified as a safety hazard.\n\n"
        )
        concern += task.problem_description
        issue = SafetyIssue.objects.create(reporter=user, location=task.tool.location, concern=concern)
        send_safety_email_notification(request, issue)

    send_new_task_emails(request, task, user, task_images)
    set_task_status(request, task, request.POST.get("status"), user)


def send_new_task_emails(request, task: Task, user, task_images: List[TaskImages]):
    message = get_media_file_contents("new_task_email.html")
    attachments = None
    if task_images:
        attachments = [create_email_attachment(task_image.image, task_image.image.name) for task_image in task_images]
    # Email the appropriate staff that a new task has been created:
    if message:
        dictionary = {
            "template_color": (
                bootstrap_primary_color("danger") if task.force_shutdown else bootstrap_primary_color("warning")
            ),
            "user": user,
            "task": task,
            "tool": task.tool,
            "tool_control_absolute_url": get_full_url(task.tool.get_absolute_url(), request),
        }
        subject = (
            ("SAFETY HAZARD: " if task.safety_hazard else "")
            + task.tool.name
            + (" shutdown" if task.force_shutdown else " problem")
        )
        message = render_email_template(message, dictionary, request)
        recipients = get_task_email_recipients(task, new=True)
        if ToolCustomization.get_bool("tool_problem_send_to_all_qualified_users"):
            recipients = set(recipients)
            for user in task.tool.user_set.all():
                if user.is_active:
                    recipients.update(
                        [email for email in user.get_emails(user.get_preferences().email_send_task_updates)]
                    )
        send_mail(
            subject=subject,
            content=message,
            from_email=user.email,
            to=recipients,
            attachments=attachments,
            email_category=EmailCategory.TASKS,
        )

    # Email any user (excluding staff) with a future reservation on the tool:
    user_office_email = EmailsCustomization.get("user_office_email_address")
    message = get_media_file_contents("reservation_warning_email.html")
    if user_office_email and message:
        upcoming_reservations = Reservation.objects.filter(
            start__gt=timezone.now(), cancelled=False, tool=task.tool, user__is_staff=False
        )
        for reservation in upcoming_reservations:
            if not task.tool.operational:
                subject = reservation.tool.name + " reservation problem"
                rendered_message = render_email_template(
                    message,
                    {
                        "reservation": reservation,
                        "template_color": bootstrap_primary_color("danger"),
                        "fatal_error": True,
                    },
                    request,
                )
            else:
                subject = reservation.tool.name + " reservation warning"
                rendered_message = render_email_template(
                    message,
                    {
                        "reservation": reservation,
                        "template_color": bootstrap_primary_color("warning"),
                        "fatal_error": False,
                    },
                    request,
                )
            email_notification = reservation.user.get_preferences().email_send_reservation_emails
            reservation.user.email_user(
                subject=subject,
                message=rendered_message,
                from_email=user_office_email,
                email_category=EmailCategory.TASKS,
                email_notification=email_notification,
            )


@login_required
@require_POST
def cancel(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    if task.cancelled or task.resolved:
        dictionary = {
            "title": "Task cancellation failed",
            "heading": "You cannot cancel this task",
            "content": "The status of this task has been changed so you may no longer cancel it.",
        }
        return render(request, "acknowledgement.html", dictionary)
    if task.creator.id != request.user.id:
        dictionary = {
            "title": "Task cancellation failed",
            "heading": "You cannot cancel this task",
            "content": "You may only cancel a tasks that you created.",
        }
        return render(request, "acknowledgement.html", dictionary)
    task.cancelled = True
    task.resolver = request.user
    task.resolution_time = timezone.now()
    task.save()
    determine_tool_status(task.tool)
    send_task_updated_email(task, get_full_url(task.tool.get_absolute_url(), request))
    return redirect("tool_control")


def send_task_updated_email(task, url, task_images: List[TaskImages] = None):
    try:
        recipients = get_task_email_recipients(task)
        attachments = None
        if task_images:
            attachments = [
                create_email_attachment(task_image.image, task_image.image.name) for task_image in task_images
            ]
        task.refresh_from_db()
        if task.cancelled:
            task_user = task.resolver
            task_status = "cancelled"
        elif task.resolved:
            task_user = task.resolver
            task_status = "resolved"
        else:
            task_user = task.last_updated_by
            task_status = "updated"
        message = f"""
A task for the {task.tool} was just modified by {task_user}.
{('<br><br>Estimated resolution:' + format_datetime(task.estimated_resolution_time)) if task.estimated_resolution_time else ''}
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
        send_mail(
            subject=f"{task.tool} task {task_status}",
            content=message,
            from_email=task_user.email,
            to=recipients,
            attachments=attachments,
            email_category=EmailCategory.TASKS,
        )
    except Exception as error:
        site_title = ApplicationCustomization.get("site_title")
        error_message = (
            f"{site_title} was unable to send the task updated email. The error message that was received is: "
            + str(error)
        )
        tasks_logger.exception(error_message)


@staff_member_required
@require_POST
def update(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    images_form = TaskImagesForm(request.POST, request.FILES)
    form = TaskForm(request.user, data=request.POST, instance=task)
    next_page = request.POST.get("next_page", "tool_control")
    if not form.is_valid() or not images_form.is_valid():
        errors = nice_errors(form)
        errors.update(nice_errors(images_form))
        dictionary = {
            "title": "Task update failed",
            "heading": "Invalid task form data",
            "content": errors.as_ul(),
        }
        return render(request, "acknowledgement.html", dictionary)
    form.save()
    set_task_status(request, task, request.POST.get("status"), request.user)
    determine_tool_status(task.tool)
    task_images = save_task_images(request, task)
    send_task_updated_email(task, get_full_url(task.tool.get_absolute_url(), request), task_images)
    if next_page == "maintenance":
        return redirect("maintenance")
    else:
        return redirect("tool_control")


@staff_member_required
@require_GET
def task_update_form(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    categories = TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT)
    dictionary = {
        "categories": categories,
        "urgency": Task.Urgency.Choices,
        "task": task,
        "estimated_resolution_time": (
            as_timezone(task.estimated_resolution_time) if task.estimated_resolution_time else None
        ),
        "task_statuses": TaskStatus.objects.all(),
    }
    return render(request, "tasks/update.html", dictionary)


@staff_member_required
@require_GET
def task_resolution_form(request, task_id):
    task = get_object_or_404(Task, id=task_id)
    categories = TaskCategory.objects.filter(stage=TaskCategory.Stage.COMPLETION)
    dictionary = {
        "categories": categories,
        "task": task,
        "estimated_resolution_time": (
            as_timezone(task.estimated_resolution_time) if task.estimated_resolution_time else None
        ),
    }
    return render(request, "tasks/resolve.html", dictionary)


def set_task_status(request, task, status_name, user):
    if not status_name:
        return

    if not user.is_staff:
        raise ValueError("Only staff can set task status")

    status = TaskStatus.objects.get(name=status_name)
    TaskHistory.objects.create(task=task, status=status_name, user=user)

    status_message = f'On {format_datetime()}, {user.get_full_name()} set the status of this task to "{status_name}".'
    task.progress_description = (
        status_message if task.progress_description is None else task.progress_description + "\n\n" + status_message
    )
    task.save()

    message = get_media_file_contents("task_status_notification.html")
    # Email the appropriate staff that a task status has been updated:
    if message:
        dictionary = {
            "template_color": bootstrap_primary_color("success"),
            "title": f"{task.tool} task notification",
            "status_message": status_message,
            "notification_message": status.notification_message,
            "task": task,
            "tool_control_absolute_url": get_full_url(task.tool.get_absolute_url(), request),
        }
        subject = f"{task.tool} task notification"
        message = render_email_template(message, dictionary, request)
        # Add primary owner if applicable
        recipient_users: List[User] = [task.tool.primary_owner] if status.notify_primary_tool_owner else []
        if status.notify_backup_tool_owners:
            # Add backup owners
            recipient_users.extend(task.tool.backup_owners.all())
        recipients = [
            email
            for user in recipient_users
            for email in user.get_emails(user.get_preferences().email_send_task_updates)
        ]
        if status.notify_tool_notification_email:
            # Add tool notification email
            recipients.append(task.tool.notification_email_address)
        recipients.append(status.custom_notification_email_address)
        send_mail(
            subject=subject, content=message, from_email=user.email, to=recipients, email_category=EmailCategory.TASKS
        )


def save_task_images(request, task: Task) -> List[TaskImages]:
    task_images: List[TaskImages] = []
    try:
        images_form = TaskImagesForm(request.POST, request.FILES)
        max_size_pixels = ToolCustomization.get_int("tool_problem_max_image_size_pixels")
        if images_form.is_valid() and images_form.cleaned_data["image"] is not None:
            for image_memory_file in request.FILES.getlist("image"):
                resized_image = resize_image(image_memory_file, max_size_pixels)
                image = TaskImages(task=task)
                image.image.save(resized_image.name, ContentFile(resized_image.read()), save=False)
                image.save()
                task_images.append(image)
    except Exception as e:
        tasks_logger.exception(e)
    return task_images


def get_task_email_recipients(task: Task, new=False) -> List[str]:
    # Add all recipients, starting with primary owner
    recipient_users: Set[User] = {task.tool.primary_owner}
    # Add backup owners
    recipient_users.update(task.tool.backup_owners.all())
    if ToolCustomization.get_bool("tool_task_updates_superusers"):
        recipient_users.update(task.tool.superusers.all())
    # Add facility managers and take into account their preferences
    if ToolCustomization.get_bool("tool_task_updates_facility_managers"):
        recipient_users.update(
            User.objects.filter(is_active=True, is_facility_manager=True).filter(
                Q(preferences__tool_task_notifications__isnull=True)
                | Q(preferences__tool_task_notifications__in=[task.tool])
            )
        )
    # Add staff/service personnel with preferences set to receive notifications for this tool
    recipient_users.update(
        User.objects.filter(is_active=True)
        .filter(Q(is_staff=True) | Q(is_service_personnel=True))
        .filter(Q(preferences__tool_task_notifications__in=[task.tool]))
    )
    # Add regular users with preferences set to receive notifications for this tool if it's allowed
    send_email_to_regular_user = (
        new
        and ToolCustomization.get_bool("tool_problem_allow_regular_user_preferences")
        or not new
        and ToolCustomization.get_bool("tool_task_updates_allow_regular_user_preferences")
    )
    if send_email_to_regular_user:
        recipient_users.update(
            User.objects.filter(is_active=True).filter(Q(preferences__tool_task_notifications__in=[task.tool]))
        )
    recipients = [
        email for user in recipient_users for email in user.get_emails(user.get_preferences().email_send_task_updates)
    ]
    if task.tool.notification_email_address:
        recipients.append(task.tool.notification_email_address)
    return recipients
