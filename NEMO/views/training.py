import datetime
from logging import getLogger
from re import search
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from NEMO.decorators import staff_member_or_tool_superuser_required
from NEMO.exceptions import ProjectChargeException
from NEMO.models import MembershipHistory, Project, Tool, ToolQualificationGroup, TrainingSession, User
from NEMO.policy import policy_class as policy
from NEMO.utilities import datetime_input_format
from NEMO.views.customization import TrainingCustomization, CalendarCustomization
from NEMO.views.users import get_identity_service

training_logger = getLogger(__name__)


@staff_member_or_tool_superuser_required
@require_GET
def training(request):
    """Present a web page to allow staff or tool superusers to charge training and qualify users on particular tools."""
    user: User = request.user
    users = User.objects.filter(is_active=True).exclude(id=user.id)
    tools = Tool.objects.filter(visible=True)
    tool_groups = ToolQualificationGroup.objects.all()
    if not user.is_staff and user.is_tool_superuser:
        tools = tools.filter(_superusers__in=[user])
        # Superusers can only use groups if they are superusers for all those
        tool_groups = (
            tool_groups.annotate(num_tools=Count("tools")).filter(tools__in=tools).filter(num_tools=len(tools))
        )
    training_types = TrainingSession.Type.Choices
    training_only_type = TrainingCustomization.get_int("training_only_type")
    if training_only_type is not None:
        # only keep the one type
        training_types = [training_type for training_type in training_types if training_type[0] == training_only_type]
    return render(
        request,
        "training/training.html",
        {
            "users": users,
            "tools": list(tools),
            "tool_groups": list(tool_groups),
            "charge_types": training_types,
            "calendar_first_day_of_week": CalendarCustomization.get("calendar_first_day_of_week"),
        },
    )


@staff_member_or_tool_superuser_required
@require_GET
def training_entry(request):
    entry_number = int(request.GET["entry_number"])
    return render(
        request,
        "training/training_entry.html",
        {"entry_number": entry_number, "charge_types": TrainingSession.Type.Choices},
    )


def is_valid_field(field):
    return (
        search("^(chosen_user|chosen_tool|chosen_project|date|duration|charge_type|qualify)__[0-9]+$", field)
        is not None
    )


@staff_member_or_tool_superuser_required
@require_POST
def charge_training(request):
    trainer: User = request.user
    date_allowed = TrainingCustomization.get_bool("training_allow_date")
    try:
        charges = {}
        for key, value in request.POST.items():
            if is_valid_field(key):
                attribute, separator, index = key.partition("__")
                index = int(index)
                if index not in charges:
                    charges[index] = TrainingSession()
                    charges[index].trainer = trainer
                if attribute == "chosen_user":
                    charges[index].trainee = User.objects.get(id=to_int_or_negative(value))
                if attribute == "chosen_tool":
                    chosen_type = request.POST.get(f"chosen_type{separator}{index}", "tool")
                    identifier = to_int_or_negative(value)
                    setattr(
                        charges[index],
                        "qualify_tools",
                        (
                            [Tool.objects.get(id=identifier)]
                            if chosen_type == "tool"
                            else ToolQualificationGroup.objects.get(id=identifier).tools.all()
                        ),
                    )
                    # Even with a group of tools, we only charge training on the first one
                    charges[index].tool = next(iter(charges[index].qualify_tools))
                    if not trainer.is_staff and trainer.is_tool_superuser:
                        if not set(charges[index].qualify_tools).issubset(trainer.superuser_for_tools.all()):
                            return HttpResponseBadRequest("The trainer is not authorized to train on this tool")
                if attribute == "chosen_project":
                    charges[index].project = Project.objects.get(id=to_int_or_negative(value))
                if attribute == "duration":
                    charges[index].duration = int(value)
                if value and attribute == "date" and date_allowed:
                    charges[index].date = datetime.datetime.strptime(value, datetime_input_format).astimezone()
                if attribute == "charge_type":
                    charges[index].type = int(value)
                if attribute == "qualify":
                    charges[index].qualified = value == "on"
        for c in charges.values():
            c.full_clean()
            policy.check_billing_to_project(c.project, c.trainee, c.tool, c)
    except ProjectChargeException as e:
        return HttpResponseBadRequest(e.msg)
    except User.DoesNotExist:
        return HttpResponseBadRequest("Please select a trainee from the list")
    except Tool.DoesNotExist:
        return HttpResponseBadRequest("Please select a tool/group from the list")
    except ToolQualificationGroup.DoesNotExist:
        return HttpResponseBadRequest("Please select a tool/group from the list")
    except Project.DoesNotExist:
        return HttpResponseBadRequest("Please select a project from the list")
    except Exception as e:
        training_logger.exception(e)
        return HttpResponseBadRequest(
            "An error occurred while processing the training charges. None of the charges were committed to the database. Please review the form for errors and omissions then submit the form again."
        )
    else:
        for c in charges.values():
            if c.qualified:
                for tool in c.qualify_tools:
                    qualify(c.trainer, c.trainee, tool)
            c.save()
        dictionary = {
            "title": "Success!",
            "content": "Training charges were successfully saved.",
            "redirect": reverse("landing"),
        }
        return render(request, "display_success_and_redirect.html", dictionary)


def qualify(authorizer, user, tool):
    if tool in user.qualifications.all():
        return
    user.qualifications.add(tool)
    entry = MembershipHistory()
    entry.authorizer = authorizer
    entry.parent_content_object = tool
    entry.child_content_object = user
    entry.action = entry.Action.ADDED
    entry.save()

    if tool.grant_physical_access_level_upon_qualification:
        if tool.grant_physical_access_level_upon_qualification not in user.accessible_access_levels().all():
            user.physical_access_levels.add(tool.grant_physical_access_level_upon_qualification)
            entry = MembershipHistory()
            entry.authorizer = authorizer
            entry.parent_content_object = tool.grant_physical_access_level_upon_qualification
            entry.child_content_object = user
            entry.action = entry.Action.ADDED
            entry.save()

    if get_identity_service().get("available", False):
        if tool.grant_badge_reader_access_upon_qualification:
            parameters = {
                "username": user.username,
                "domain": user.domain,
                "requested_area": tool.grant_badge_reader_access_upon_qualification,
            }
            timeout = settings.IDENTITY_SERVICE.get("timeout", 3)
            requests.put(urljoin(settings.IDENTITY_SERVICE["url"], "/add/"), data=parameters, timeout=timeout)


def to_int_or_negative(value: str):
    try:
        return int(value)
    except ValueError:
        return -1
