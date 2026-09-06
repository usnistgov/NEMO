from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from NEMO.models import (
    Comment,
    SafetyIssue,
    StaffKnowledgeBaseItem,
    Task,
    User,
    UserKnowledgeBaseItem,
    UserReaction,
    set_user_reaction,
)
from NEMO.views.customization import KnowledgeBaseCustomization, SafetyCustomization, ToolCustomization

# Models that support user reactions: the model class, the permission check required for a user to react to an
# instance of it, and the customization check for whether reactions are enabled for this content type at all.
REACTABLE_MODELS = {
    "task": (
        Task,
        lambda user, obj: True,
        lambda: ToolCustomization.get_bool("tool_task_reactions_enabled"),
    ),
    "safetyissue": (
        SafetyIssue,
        lambda user, obj: True,
        lambda: SafetyCustomization.get_bool("safety_issue_reactions_enabled"),
    ),
    "comment": (
        Comment,
        lambda user, obj: True,
        lambda: ToolCustomization.get_bool("tool_comment_reactions_enabled"),
    ),
    "userknowledgebaseitem": (
        UserKnowledgeBaseItem,
        lambda user, obj: True,
        lambda: KnowledgeBaseCustomization.get_bool("knowledge_base_user_reactions_enabled"),
    ),
    "staffknowledgebaseitem": (
        StaffKnowledgeBaseItem,
        lambda user, obj: user.is_any_part_of_staff,
        lambda: KnowledgeBaseCustomization.get_bool("knowledge_base_staff_reactions_enabled"),
    ),
}


@login_required
@require_POST
def toggle_reaction(request, model_name: str, object_id: int):
    model_name = model_name.lower()
    if model_name not in REACTABLE_MODELS:
        return HttpResponseBadRequest("Unsupported content type for reactions.")
    model_class, is_authorized, is_enabled = REACTABLE_MODELS[model_name]
    if not is_enabled():
        return HttpResponseBadRequest("Reactions are disabled for this type of content.")
    obj = get_object_or_404(model_class, id=object_id)
    user: User = request.user
    if not is_authorized(user, obj):
        return HttpResponseBadRequest("You are not authorized to react to this item.")
    try:
        reaction = int(request.POST.get("reaction", UserReaction.Reaction.HELPFUL))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid reaction value.")
    if reaction not in dict(UserReaction.Reaction.Choices):
        return HttpResponseBadRequest("Invalid reaction value.")
    current_reaction, counts = set_user_reaction(obj, user, reaction)
    return JsonResponse({"reaction": current_reaction, **counts})
