from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from NEMO.decorators import staff_member_required
from NEMO.models import ToolCredentials, User


@staff_member_required
@require_GET
def tool_credentials_list(request):
    user: User = request.user
    tool_credentials = ToolCredentials.objects.filter(tool__visible=True)
    if not user.is_facility_manager:
        tool_credentials = tool_credentials.filter(Q(authorized_staff__isnull=True) | Q(authorized_staff__in=[user]))
    return render(request, "tool_credentials/tool_credentials.html", {"tool_credentials": tool_credentials})
