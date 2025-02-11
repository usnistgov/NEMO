import importlib.metadata
from logging import getLogger
from typing import List, Optional, Tuple, Union

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Field
from django.http import HttpResponse
from django.shortcuts import render
from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

utils_logger = getLogger(__name__)


# Useful function to render and combine 2 separate django templates
def render_combine_responses(request, original_response: HttpResponse, template_name, context):
    """Combines contents of an original http response with a new one"""
    additional_content = render(request, template_name, context)
    original_response.content += additional_content.content
    return original_response


# Checks that at least one requirement in the list is satisfied and returns the first one
def is_any_requirement_satisfied(
    requirements: List[Union[Requirement, str]], prereleases=False
) -> Optional[Requirement]:
    for requirement in requirements:
        try:
            if isinstance(requirement, str):
                requirement = Requirement(requirement)
            dist_version = importlib.metadata.version(requirement.name)
            if check_version_satisfies(dist_version, requirement, prereleases):
                return requirement
        except (importlib.metadata.PackageNotFoundError, InvalidVersion):
            continue
    return None


def check_version_satisfies(installed_version, requirement, prereleases=False) -> bool:
    """Check if the installed version satisfies the requirement."""
    installed_version = Version(installed_version)
    for specifier in requirement.specifier:
        if not specifier.contains(installed_version, prereleases=prereleases):
            return False
    return True


def get_extra_requires(app_name, extra_name: str) -> List[Requirement]:
    requirements: List[Requirement] = []
    distribution = importlib.metadata.distribution(app_name)
    requires = distribution.requires or []
    for req in requires:
        requirement = Requirement(req)
        if requirement.marker and requirement.marker.evaluate({"extra": extra_name}):
            requirements.append(requirement)
    return requirements


# Use this function in apps config ready function to add new types of notifications
def add_dynamic_notification_types(notification_types: List[Tuple[str, str]]):
    from NEMO.models import Notification, LandingPageChoice

    add_dynamic_choices_to_choice_field(Notification._meta.get_field("notification_type"), notification_types)
    add_dynamic_choices_to_choice_field(LandingPageChoice._meta.get_field("notifications"), notification_types)


# Use this function in apps config ready function to add new types of email categories
def add_dynamic_email_categories(email_categories: List[Tuple[int, str]]):
    from NEMO.models import EmailLog

    add_dynamic_choices_to_choice_field(EmailLog._meta.get_field("category"), email_categories)


def add_dynamic_choices_to_choice_field(field: Field, new_choices: List[Tuple[Union[str, int], str]]):
    try:
        original_choices = list(field.choices)

        for new_choice in new_choices:
            if new_choice not in original_choices:
                original_choices.append(new_choice)
        field.choices = original_choices
    except FieldDoesNotExist:
        utils_logger.exception("Error adding dynamic choices: {}".format(new_choices))
