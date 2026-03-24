from typing import List, Tuple

from django.apps import apps
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test import Client, TestCase
from requests import Response

from NEMO.models import Account, Project, User
from NEMO.views.customization import CustomizationBase


class NEMOTestCaseMixin:
    """
    A mixin class providing utilities and common functionalities for testing in the NEMO framework.

    This class is intended to be used as a mixin alongside test cases to streamline repetitive tasks
    often encountered in testing, such as authentication, model validation, and response assertion.
    It provides helper methods for managing test states, user logins, and validating responses.

    Methods
    -------
    tearDown():
        Clears cached data and cleans up resources after each test case execution.

    login_as(user):
        Logs in a specified user for testing.

    login_as_staff() -> User:
        Logs in a staff user and returns the authenticated user object.

    login_as_user():
        Logs in a general user for testing.

    login_as_user_with_permissions(permissions):
        Logs in a user with specified permissions for testing.

    validate_model_error(model, error_fields, strict):
        Validates model errors given specific fields and strictness.

    assert_response_is_login_page(response):
        Asserts that the provided response corresponds to the login page.

    assert_response_is_failed_login(response):
        Asserts that the provided response corresponds to a failed login attempt.

    assert_response_is_landing_page(response):
        Asserts that the provided response corresponds to the landing page.
    """

    def tearDown(self):
        # Clear the cache after each test case execution
        CustomizationBase.invalidate_cache()
        # Make sure to call the parent tearDown method to preserve functionality
        super().tearDown()

    def login_as(self, user: User):
        login_as(self.client, user)

    def login_as_staff(self) -> User:
        return login_as_staff(self.client)

    def login_as_user(self):
        return login_as_user(self.client)

    def login_as_user_with_permissions(self, permissions: List[str]):
        return login_as_user_with_permissions(self.client, permissions)

    def validate_model_error(self, model, error_fields, strict=False):
        validate_model_error(self, model, error_fields, strict)

    def assert_response_is_login_page(self, response: Response):
        test_response_is_login_page(self, response)

    def assert_response_is_failed_login(self, response: Response):
        test_response_is_failed_login(self, response)

    def assert_response_is_landing_page(self, response: Response):
        test_response_is_landing_page(self, response)


def login_as(client: Client, user: User):
    client.force_login(user)


def login_as_staff(client: Client) -> User:
    tester, created = User.objects.get_or_create(
        username="test_staff", first_name="Test", last_name="Staff", is_staff=True, badge_number=111111
    )
    login_as(client, tester)
    return tester


def login_as_user(client: Client) -> User:
    user, created = User.objects.get_or_create(
        username="test_user", first_name="Testy", last_name="McTester", badge_number=222222
    )
    login_as(client, user)
    return user


def login_as_user_with_permissions(client: Client, permissions: List[str]) -> User:
    user, created = User.objects.get_or_create(
        username="test_user", first_name="Testy", last_name="McTester", badge_number=222222
    )
    for permission in Permission.objects.filter(codename__in=permissions):
        user.user_permissions.add(permission)
    user.save()
    login_as(client, user)
    return user


def validate_model_error(test_case: TestCase, model, error_fields, strict=False):
    try:
        model.full_clean()
        test_case.fail(f"Should have failed with error fields: {error_fields}")
    except ValidationError as e:
        for error_field in error_fields:
            test_case.assertIn(error_field, e.error_dict)
        if strict:
            diff1 = set(error_fields).difference(e.error_dict.keys())
            diff2 = set(e.error_dict.keys()).difference(error_fields)
            if diff1:
                test_case.fail(f"{diff1} don't have errors but should")
            if diff2:
                test_case.fail(f"{diff2} have errors but shouldn't")


def create_user_and_project(
    is_staff=False, add_kiosk_permission=False, add_area_access_permissions=False
) -> Tuple[User, Project]:
    count = User.objects.count()
    user: User = User.objects.create(
        first_name="Testy",
        last_name="McTester",
        username=f"test{count}",
        email=f"test{count}@test.com",
        is_staff=is_staff,
    )
    if add_kiosk_permission:
        user.user_permissions.add(Permission.objects.get(codename="kiosk"))
    if add_area_access_permissions:
        user.user_permissions.add(Permission.objects.get(codename="add_areaaccessrecord"))
        user.user_permissions.add(Permission.objects.get(codename="change_areaaccessrecord"))
    project = Project.objects.create(
        name=f"TestProject{count}", account=Account.objects.create(name=f"TestAccount{count}")
    )
    user.projects.add(project)
    return user, project


def test_response_is_login_page(test_case: TestCase, response: Response):
    test_case.assertEqual(response.status_code, 200)
    test_case.assertTrue("login" in response.request["PATH_INFO"])


def test_response_is_failed_login(test_case: TestCase, response: Response):
    test_case.assertContains(response=response, text="There was an error pre-authenticating the user", status_code=400)


def test_response_is_landing_page(test_case: TestCase, response: Response):
    test_case.assertEqual(response.status_code, 200)
    test_case.assertEqual(response.request["PATH_INFO"], "/")


def reset_all_oracle_sequences():
    if connection.vendor == "oracle":
        with connection.cursor() as cursor:
            for model in apps.get_models(include_auto_created=True):
                # Skip abstract models, unmanaged models, or views
                if not model._meta.managed:
                    continue

                pk_field = model._meta.pk

                # We ONLY want to reset fields that are actually auto-incrementing IDs.
                # This skips UUID fields, String primary keys, etc.
                if not isinstance(pk_field, (models.AutoField, models.BigAutoField, models.SmallAutoField)):
                    continue
                table_name = connection.ops.quote_name(model._meta.db_table)
                pk_column = connection.ops.quote_name(model._meta.pk.column)

                # Oracle syntax to reset an identity column to 1
                sql = f"ALTER TABLE {table_name} MODIFY ({pk_column} GENERATED BY DEFAULT ON NULL AS IDENTITY (START WITH 1))"
                try:
                    cursor.execute(sql)
                except Exception as e:
                    print(f"Could not reset sequence for {table_name}: {e}")
