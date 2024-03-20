from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET

from NEMO.models import (
    StaffKnowledgeBaseCategory,
    StaffKnowledgeBaseItem,
    User,
    UserKnowledgeBaseCategory,
    UserKnowledgeBaseItem,
)
from NEMO.utilities import distinct_qs_value_list, queryset_search_filter
from NEMO.views.customization import KnowledgeBaseCustomization


@login_required
@require_GET
def knowledge_base(request, kind="user"):
    return (
        redirect(f"knowledge_base_categories", kind=kind)
        if not KnowledgeBaseCustomization.get_bool(f"knowledge_base_{kind}_expand_categories")
        else redirect(f"knowledge_base_all_in_one", kind=kind)
    )


@login_required
@require_GET
def knowledge_base_all_in_one(request, kind="user"):
    user: User = request.user
    if kind == "staff" and not user.is_any_part_of_staff:
        return redirect("landing")
    item_model = StaffKnowledgeBaseItem if kind == "staff" else UserKnowledgeBaseItem
    category_model = StaffKnowledgeBaseCategory if kind == "staff" else UserKnowledgeBaseCategory
    dictionary = {
        "kind": kind,
        "categories": category_model.objects.filter(
            id__in=distinct_qs_value_list(item_model.objects.all(), "category_id")
        ),
        "general": item_model.objects.filter(category__isnull=True),
        "expand_categories": True,
    }
    return render(request, "knowledge_base/knowledge_base.html", dictionary)


@login_required
@require_GET
def knowledge_base_categories(request, kind="user", category_id=None):
    user: User = request.user
    if kind == "staff" and not user.is_any_part_of_staff:
        return redirect("landing")
    item_model = StaffKnowledgeBaseItem if kind == "staff" else UserKnowledgeBaseItem
    category_model = StaffKnowledgeBaseCategory if kind == "staff" else UserKnowledgeBaseCategory
    try:
        item_id = request.GET.get("item_id")
        if item_id:
            category_id = item_model.objects.get(pk=item_id).category_id
        category_model.objects.get(pk=category_id)
    except category_model.DoesNotExist:
        pass
    items_qs = item_model.objects.filter(category_id=category_id)
    if not category_id and not items_qs.exists():
        first_category = category_model.objects.first()
        category_id = first_category.id if first_category else None
    dictionary = {
        "kind": kind,
        "category_id": category_id,
        "items": item_model.objects.filter(category_id=category_id),
        "categories": category_model.objects.filter(
            id__in=distinct_qs_value_list(item_model.objects.all(), "category_id")
        ),
        "general": item_model.objects.filter(category_id__isnull=True).exists(),
    }
    return render(request, "knowledge_base/knowledge_base.html", dictionary)


@login_required
@require_GET
def knowledge_base_item(request, item_id: int, kind="user"):
    # Redirect to the appropriate URL with hashtag included to scroll to the item
    user: User = request.user
    if kind == "staff" and not user.is_any_part_of_staff:
        return redirect("landing")
    url_params = f"?item_id={item_id}#item_{item_id}"
    redirect_url = (
        reverse(f"knowledge_base_categories", kwargs={"kind": kind})
        if not KnowledgeBaseCustomization.get_bool(f"knowledge_base_{kind}_expand_categories")
        else reverse(f"knowledge_base_all_in_one", kwargs={"kind": kind})
    )
    return redirect(redirect_url + url_params)


@login_required
@require_GET
def knowledge_base_items_search(request, kind="user"):
    user: User = request.user
    if kind == "staff" and not user.is_any_part_of_staff:
        return redirect("landing")
    item_model = StaffKnowledgeBaseItem if kind == "staff" else UserKnowledgeBaseItem
    return queryset_search_filter(item_model.objects.all(), ["name", "description"], request)
