from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import facility_manager_required, staff_member_required
from NEMO.models import ToolCredentials, User
from NEMO.utilities import BasicDisplayTable, export_format_datetime


@staff_member_required
@require_GET
def tool_credentials_list(request):
    user: User = request.user
    tool_credentials = ToolCredentials.objects.filter(tool__visible=True)
    if not user.is_facility_manager:
        tool_credentials = tool_credentials.filter(Q(authorized_staff__isnull=True) | Q(authorized_staff__in=[user]))
    return render(request, "tool_credentials/tool_credentials.html", {"tool_credentials": tool_credentials})


@facility_manager_required
@require_GET
def export_tool_credentials(request):
    table = BasicDisplayTable()
    table.headers = [
        ("tool", "Tool"),
        ("username", "Username"),
        ("password", "Password"),
        ("comments", "Comments"),
        ("authorized_staff", "Authorized staff"),
    ]
    for tool_cred in ToolCredentials.objects.all():
        tool_cred: ToolCredentials = tool_cred
        table.add_row(
            {
                "tool": tool_cred.tool.name,
                "username": tool_cred.username,
                "password": tool_cred.password,
                "comments": tool_cred.comments,
                "authorized_staff": (
                    "\n".join([authorized_user for authorized_user in tool_cred.authorized_staff.all()])
                    if tool_cred.authorized_staff.exists()
                    else "All"
                ),
            }
        )
    filename = f"tool_credentials_{export_format_datetime()}.csv"
    response = table.to_csv()
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
