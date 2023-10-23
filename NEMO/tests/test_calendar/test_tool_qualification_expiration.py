from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from NEMO.models import Account, EmailLog, Project, Qualification, Tool, UsageEvent, User
from NEMO.views.customization import EmailsCustomization, ToolCustomization
from NEMO.views.timed_services import do_manage_tool_qualifications


@patch("django.core.files.storage.FileSystemStorage.exists")
@patch("django.core.files.storage.FileSystemStorage._open")
class ToolQualificationTestCase(TestCase):
    def setUp(self):
        self.manager: User = User.objects.create(
            username="manager",
            first_name="Facility",
            last_name="Manager",
            email="facility.manager@example.com",
            is_facility_manager=True,
        )
        self.owner: User = User.objects.create(
            username="mctest", first_name="Testy", last_name="McTester", email="testy.mctester@example.com"
        )
        self.user: User = User.objects.create(
            username="user", first_name="User", last_name="McTester", email="user.mctester@example.com"
        )
        self.project: Project = Project.objects.create(
            name="Project 1", application_identifier="P1", account=Account.objects.create(name="Account 1")
        )
        self.user.projects.add(self.project)
        self.tool: Tool = Tool.objects.create(name="test_tool", primary_owner=self.owner, _category="Imaging")

    def test_qualification_expiration_disabled_no_days(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        usage_date = timezone.now() - timedelta(days=3)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        # Never used days set but not regular days
        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_expiration_disabled_no_never_used_days(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        # Expiration days are set but never used days are not
        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_expiration_disabled_no_email(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        ToolCustomization.set("tool_qualification_expiration_days", 3)
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_expiration_disabled_no_template(self, mock_open, mock_exist):
        mock_exist.return_value = False
        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_expiration_tool_exempt(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")

        # Tool is exempt
        self.tool._qualifications_never_expire = True
        self.tool.save()

        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_not_expired(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        usage_date = timezone.now() - timedelta(days=2)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since tool use)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_not_expired_never_used(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since qualification)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())

    def test_qualification_expired(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = date.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        usage_date = timezone.now() - timedelta(days=3)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was removed
        self.assertFalse(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email was sent
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_retrain_not_expired(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = date.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        usage_date = timezone.now() - timedelta(days=3)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was not removed (qualified later than usage)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email was not sent
        self.assertFalse(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_expired_never_used(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=3)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was removed
        self.assertFalse(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email was sent
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_expired_a_while(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=20)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        usage_date = timezone.now() - timedelta(days=20)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        ToolCustomization.set("tool_qualification_cc", "qualif_cc@example.com")
        # Set alternate email for user
        prefs = self.user.get_preferences()
        prefs.email_alternate = "user.alternate@example.com"
        prefs.save()
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was removed
        self.assertFalse(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email was sent to both user's emails
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=prefs.email_alternate).exists()
        )
        # Email was sent to cc address
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains="qualif_cc@example.com").exists()
        )

    def test_qualification_expired_a_while_never_used(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=20)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        ToolCustomization.set("tool_qualification_cc", "qualif_cc@example.com")
        # Set alternate email for user
        prefs = self.user.get_preferences()
        prefs.email_alternate = "user.alternate@example.com"
        prefs.save()
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was removed
        self.assertFalse(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email was sent to both user's emails
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=prefs.email_alternate).exists()
        )
        # Email was sent to cc address
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains="qualif_cc@example.com").exists()
        )

    def test_qualification_reminders_wrong_day(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        usage_date = timezone.now() - timedelta(days=2)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        # Set reminder 2 days before expiration
        ToolCustomization.set("tool_qualification_reminder_days", 2)
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since qualification)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email reminder was not sent (not 2 days before yet)
        self.assertFalse(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_reminders_wrong_day_never_used(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        # Set reminder 2 days before expiration
        ToolCustomization.set("tool_qualification_reminder_days", 2)
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since qualification)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email reminder was not sent (not 2 days before yet)
        self.assertFalse(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_reminders_ok(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")
        usage_date = timezone.now() - timedelta(days=2)
        UsageEvent.objects.create(
            user=self.user, operator=self.user, tool=self.tool, project=self.project, start=usage_date
        )

        ToolCustomization.set("tool_qualification_expiration_days", 3)
        # Set reminder 1 day before expiration
        ToolCustomization.set("tool_qualification_reminder_days", 1)
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since qualification)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email reminder was sent
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )

    def test_qualification_reminders_ok_never_used(self, mock_open, mock_exist):
        mock_exist.return_value = True
        mock_open.return_value = ContentFile(b"Email template", name="template")
        qualification_date = datetime.today() - timedelta(days=2)
        Qualification.objects.create(tool=self.tool, user=self.user, qualified_on=qualification_date)
        EmailsCustomization.set("user_office_email_address", "user_office@example.com")

        ToolCustomization.set("tool_qualification_expiration_never_used_days", 3)
        # Set reminder 1 day before expiration
        ToolCustomization.set("tool_qualification_reminder_days", 1)
        # Trigger the expiration timed service
        do_manage_tool_qualifications()
        # Qualification was NOT removed (3 days disqualified, but only 2 days since qualification)
        self.assertTrue(Qualification.objects.filter(tool=self.tool, user=self.user).exists())
        # Email reminder was sent
        self.assertTrue(
            EmailLog.objects.filter(sender="user_office@example.com", to__contains=self.user.email).exists()
        )
