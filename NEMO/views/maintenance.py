from itertools import chain
from urllib.parse import urlencode

from django.db.models import Q
from django.http import HttpResponseNotFound
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from NEMO.decorators import staff_member_or_tool_staff_required
from NEMO.models import Task, TaskCategory, TaskStatus, Tool, User
from NEMO.utilities import as_timezone, get_tool_categories_for_filters
from NEMO.views.pagination import SortedPaginator

CLOSED_TASK_SORT_FIELDS = {
    "creation_time",
    "-creation_time",
    "resolution_time",
    "-resolution_time",
    "tool__name",
    "-tool__name",
    "urgency",
    "-urgency",
}


def filter_maintenance_records(tasks, tool_category: str, tool_id: str, search: str):
    if tool_category:
        tasks = tasks.filter(Q(tool___category=tool_category) | (Q(tool___category__startswith=tool_category + "/")))
    if tool_id:
        tasks = tasks.filter(tool_id=tool_id)
    if search:
        tasks = tasks.filter(
            Q(problem_description__icontains=search)
            | Q(progress_description__icontains=search)
            | Q(resolution_description__icontains=search)
            | Q(tool__name__icontains=search)
        )
    return tasks


@staff_member_or_tool_staff_required
@require_GET
def maintenance(request, sort_by=""):
    # The "sort_by" URL path segment is kept only for backwards compatibility with old bookmarks/links.
    # New links use the "sort_by" query parameter instead, so the browser never navigates away from the
    # plain "/maintenance/" path -- otherwise the closed tab's sort/pagination links (which are relative
    # "?..." hrefs) end up resolving against a lingering "/maintenance/<sort_by>/" path and get "stuck".
    sort_by = sort_by or request.GET.get("sort_by", "")
    user: User = request.user
    pending_tasks = Task.objects.filter(cancelled=False, resolved=False)
    if not user.is_staff:
        # restrict to tools that the user is staff for
        pending_tasks = pending_tasks.filter(tool__in=user.staff_for_tools.all())
    tool_category = request.GET.get("tool_category")
    tool_id = request.GET.get("tool")
    search = request.GET.get("search", "").strip()
    if user.get_preferences().tool_task_notifications.exists():
        # Limit tools to preferences + tools user is the owner of + tools user is a backup owner of.
        limit_tools = set(user.get_preferences().tool_task_notifications.all())
        limit_tools.update(user.primary_tool_owner.all())
        limit_tools.update(user.backup_for_tools.all())
        pending_tasks = pending_tasks.filter(tool__in=limit_tools)
    pending_tasks = filter_maintenance_records(pending_tasks, tool_category, tool_id, search)
    if sort_by in [
        "urgency",
        "force_shutdown",
        "tool",
        "tool___category",
        "problem_category",
        "last_updated",
        "creation_time",
    ]:
        if sort_by == "last_updated":
            pending_tasks = pending_tasks.exclude(last_updated=None).order_by("-last_updated")
            not_yet_updated_tasks = filter_maintenance_records(
                Task.objects.filter(cancelled=False, resolved=False, last_updated=None), tool_category, tool_id, search
            ).order_by("-creation_time")
            pending_tasks = list(chain(pending_tasks, not_yet_updated_tasks))
        else:
            pending_tasks = pending_tasks.order_by(sort_by)
            if sort_by in ["urgency", "force_shutdown", "creation_time"]:
                pending_tasks = pending_tasks.reverse()
    else:
        pending_tasks = pending_tasks.order_by("urgency").reverse()  # Order by urgency by default

    closed_tasks = Task.objects.filter(Q(cancelled=True) | Q(resolved=True)).exclude(resolution_time__isnull=True)
    closed_tasks = filter_maintenance_records(closed_tasks, tool_category, tool_id, search)
    closed_order_by = request.GET.get("o")
    if closed_order_by not in CLOSED_TASK_SORT_FIELDS:
        # SortedPaginator reads "o" straight from request.GET, so an invalid value has to be
        # corrected there too, not just in the default we pass in below
        closed_order_by = "-resolution_time"
        sanitized_get = request.GET.copy()
        sanitized_get["o"] = closed_order_by
        request.GET = sanitized_get
    closed_paginator = SortedPaginator(closed_tasks, request, order_by=closed_order_by)
    closed_page = closed_paginator.get_current_page()

    closed_extra_params = urlencode(
        {
            key: value
            for key, value in {
                "tool_category": tool_category,
                "tool": tool_id,
                "search": search,
                "tab": "closed",
            }.items()
            if value
        }
    )
    pending_extra_params = urlencode(
        {
            key: value
            for key, value in {"tool_category": tool_category, "tool": tool_id, "search": search}.items()
            if value
        }
    )

    dictionary = {
        "pending_tasks": pending_tasks,
        "closed_page": closed_page,
        "closed_extra_params": closed_extra_params,
        "pending_extra_params": pending_extra_params,
        "tool_categories": get_tool_categories_for_filters(),
        "tools": Tool.objects.all().order_by("name"),
        "tool_category": tool_category,
        "selected_tool": Tool.objects.filter(id=tool_id).first() if tool_id else None,
        "search": search,
        "tab": request.GET.get("tab", "pending"),
        "pending_sort_by": sort_by,
    }
    return render(request, "maintenance/maintenance.html", dictionary)


@staff_member_or_tool_staff_required
@require_GET
def task_details(request, task_id):
    user: User = request.user
    task = get_object_or_404(Task, id=task_id)
    if not user.is_staff and task.tool_id not in user.staff_for_tools.values_list("id", flat=True):
        return HttpResponseNotFound("Task not found")

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
        dictionary["rendered_configuration_html"] = task.tool.configuration_widget(user)

    return render(request, "maintenance/pending_task_details.html", dictionary)
