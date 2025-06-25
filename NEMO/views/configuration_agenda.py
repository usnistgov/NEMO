from datetime import timedelta

from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import staff_member_or_tool_staff_required
from NEMO.models import Configuration, Reservation, Tool, User
from NEMO.utilities import distinct_qs_value_list, localize, naive_local_current_datetime
from NEMO.views.customization import ToolCustomization


@staff_member_or_tool_staff_required
@require_GET
def configuration_agenda(request, time_period="today"):
    user: User = request.user
    tool_ids = distinct_qs_value_list(
        Configuration.objects.filter(enabled=True, exclude_from_configuration_agenda=False), "tool_id"
    )
    if not user.is_staff:
        # restrict to tools that the user is staff for
        tool_ids = [tool_id for tool_id in tool_ids if tool_id in user.staff_for_tools.values_list("id", flat=True)]
    start = None
    end = None
    if time_period == "today":
        start = naive_local_current_datetime().replace(tzinfo=None)
        end = naive_local_current_datetime().replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=None)
    elif time_period == "near_future":
        days_near_future = ToolCustomization.get_int("tool_configuration_near_future_days", 1)
        start = naive_local_current_datetime().replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=None)
        if start.weekday() == 5:
            # If it's Saturday, then the 'near future' is always "customization days" + 1 (for Sunday)
            end = start + timedelta(days=days_near_future + 1)
        elif start.weekday() < 5 <= days_near_future + start.weekday() - 1:
            # For weekdays, if the sum of today plus "customization days" falls on the weekend
            # Then the 'near future' is "customization days" + 2 (Saturday and Sunday)
            end = start + timedelta(days=days_near_future + 2)
        else:
            # Other cases, i.e. Sundays and weekdays with the sum not falling on a weekend
            end = start + timedelta(days=days_near_future)
    start = localize(start)
    end = localize(end)
    reservations = (
        Reservation.objects.filter(
            start__gt=start,
            start__lt=end,
            tool__id__in=tool_ids,
            self_configuration=False,
            cancelled=False,
            missed=False,
            shortened=False,
        )
        .exclude(configurationoption_set__isnull=True)
        .order_by("start")
    )
    tools = Tool.objects.filter(id__in=reservations.values_list("tool", flat=True))
    configuration_widgets = {}
    for tool in tools:
        configuration_widgets[tool.id] = tool.configuration_widget(user, filter_for_agenda=True)
    dictionary = {
        "time_period": time_period,
        "tools": tools,
        "reservations": reservations,
        "configuration_widgets": configuration_widgets,
    }
    return render(request, "configuration_agenda.html", dictionary)
