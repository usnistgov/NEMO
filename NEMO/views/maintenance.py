from itertools import chain

from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from NEMO.decorators import staff_member_required
from NEMO.models import Task, TaskCategory, TaskStatus, User
from NEMO.utilities import as_timezone


@staff_member_required
@require_GET
def maintenance(request, sort_by=""):
    user: User = request.user
    pending_tasks = Task.objects.filter(cancelled=False, resolved=False)
    if user.get_preferences().tool_task_notifications.exists():
        # Limit tools to preferences + tools user is the owner of + tools user is a backup owner of.
        limit_tools = set(user.get_preferences().tool_task_notifications.all())
        limit_tools.update(user.primary_tool_owner.all())
        limit_tools.update(user.backup_for_tools.all())
        pending_tasks = pending_tasks.filter(tool__in=limit_tools)
    if sort_by in ["urgency", "force_shutdown", "tool", "problem_category", "last_updated", "creation_time"]:
        if sort_by == "last_updated":
            pending_tasks = pending_tasks.exclude(last_updated=None).order_by("-last_updated")
            not_yet_updated_tasks = Task.objects.filter(cancelled=False, resolved=False, last_updated=None).order_by(
                "-creation_time"
            )
            pending_tasks = list(chain(pending_tasks, not_yet_updated_tasks))
        else:
            pending_tasks = pending_tasks.order_by(sort_by)
            if sort_by in ["urgency", "force_shutdown", "creation_time"]:
                pending_tasks = pending_tasks.reverse()
    else:
        pending_tasks = pending_tasks.order_by("urgency").reverse()  # Order by urgency by default
    closed_tasks = (
        Task.objects.filter(Q(cancelled=True) | Q(resolved=True))
        .exclude(resolution_time__isnull=True)
        .order_by("-resolution_time")[:20]
    )
    dictionary = {
        "pending_tasks": pending_tasks,
        "closed_tasks": closed_tasks,
    }
    return render(request, "maintenance/maintenance.html", dictionary)


@staff_member_required
@require_GET
def task_details(request, task_id):
    task = get_object_or_404(Task, id=task_id)

    if task.cancelled or task.resolved:
        return render(request, "maintenance/closed_task_details.html", {"task": task})

    dictionary = {
        "task": task,
        "estimated_resolution_time": (
            as_timezone(task.estimated_resolution_time) if task.estimated_resolution_time else None
        ),
        "initial_assessment_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT),
        "completion_categories": TaskCategory.objects.filter(stage=TaskCategory.Stage.COMPLETION),
        "task_statuses": TaskStatus.objects.all(),
    }

    if task.tool.is_configurable():
        dictionary["rendered_configuration_html"] = task.tool.configuration_widget(request.user)

    return render(request, "maintenance/pending_task_details.html", dictionary)
