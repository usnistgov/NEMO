from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from NEMO.admin import ClosureAdminForm
from NEMO.models import Alert, Closure, ClosureTime, Customization, EmailLog, User
from NEMO.utilities import EmailCategory
from NEMO.views.calendar import do_create_closure_alerts


class ClosuresTestCase(TestCase):
	def setUp(self):
		# We need user office email and at least one facility manager for the email to be sent
		Customization.objects.create(name="user_office_email_address", value="test@test.com")
		User.objects.create(
			first_name="Testy", last_name="McTester", email="testy@tester.com", is_active=True, is_facility_manager=True
		)

	def testAlertNoTemplate(self):
		# Try creating an alert with days_before set but no alert template (should fail)
		closure_admin = ClosureAdminForm({"name": "Closure fail", "alert_days_before": 1})
		self.assertFalse(closure_admin.is_valid())
		self.assertIn("alert_template", closure_admin.errors)

	def testClosureNoAlerts(self):
		# Create closure with no alert days before
		closure_no_alert = Closure.objects.create(name="Closure no alert")
		ClosureTime.objects.create(
			closure=closure_no_alert, start_time=timezone.now(), end_time=timezone.now() + timedelta(days=1)
		)
		do_create_closure_alerts()
		self.assertFalse(Alert.objects.filter(title=closure_no_alert.name).exists())

	def testClosureEndPast(self):
		# Create closure in the past, alert should not be created
		closure_no_alert = Closure.objects.create(name="Closure no alert", alert_days_before=1, alert_template="test")
		ClosureTime.objects.create(
			closure=closure_no_alert,
			start_time=timezone.now() - timedelta(days=4),
			end_time=timezone.now() - timedelta(days=2),
		)
		do_create_closure_alerts()
		self.assertFalse(Alert.objects.filter(title=closure_no_alert.name).exists())

	def testClosureAlertNow(self):
		# Create closure with alert
		closure = Closure.objects.create(name="Closure alert", alert_days_before=0, alert_template="test {{ name }}")
		start_time = timezone.now()
		end_time = start_time + timedelta(days=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		alert = Alert.objects.filter(title=closure.name).first()
		self.assertEqual(alert.title, closure.name)
		self.assertEqual(alert.contents, f"test {closure.name}")
		self.assertEqual(alert.expiration_time, end_time)
		self.assertEqual(alert.debut_time, start_time)
		do_create_closure_alerts()
		self.assertEqual(Alert.objects.filter(title=closure.name).count(), 1)

	def testClosureAlertTooFarOut(self):
		# Create closure with alert
		closure = Closure.objects.create(name="Closure future alert", alert_days_before=0, alert_template="test")
		start_time = timezone.now() + timedelta(weeks=2)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		self.assertFalse(Alert.objects.filter(title=closure.name).exists())

	def testClosureAlertRightOn(self):
		# Closure just a week out. Alert should be created
		closure = Closure.objects.create(name="Closure alert", alert_days_before=3, alert_template="test")
		start_time = timezone.now() + timedelta(weeks=1)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		alert = Alert.objects.filter(title=closure.name).first()
		self.assertTrue(alert)
		self.assertEqual(alert.debut_time, start_time - timedelta(days=3))

	def testClosureAlertRightAfter(self):
		# Closure a week and an hour out. Alert should not be created
		closure = Closure.objects.create(name="Closure alert", alert_days_before=0, alert_template="test")
		start_time = timezone.now() + timedelta(weeks=1) + timedelta(hours=1)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		self.assertFalse(Alert.objects.filter(title=closure.name).exists())

	def testClosureAlertRightAfterButDaysBefore(self):
		# Closure a week and a day out but with days_before set to 2. Alert should be created
		closure = Closure.objects.create(name="Closure alert", alert_days_before=2, alert_template="test")
		start_time = timezone.now() + timedelta(weeks=1) + timedelta(days=1)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		self.assertTrue(Alert.objects.filter(title=closure.name).exists())

	def testClosureStartPastEndLater(self):
		# Create closure starting in the past but ending after now, alert should be created
		closure_overlap = Closure.objects.create(name="Closure", alert_days_before=1, alert_template="test")
		start_time = timezone.now() - timedelta(weeks=1)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure_overlap, start_time=start_time, end_time=end_time)
		do_create_closure_alerts()
		self.assertTrue(Alert.objects.filter(title=closure_overlap.name).exists())

	def testMultipleClosureTimes(self):
		closure_multiple_times = Closure.objects.create(
			name="Closure multiple", alert_days_before=1, alert_template="test"
		)
		start_time = timezone.now() - timedelta(days=2)
		end_time = timezone.now() + timedelta(days=1)
		ClosureTime.objects.create(closure=closure_multiple_times, start_time=start_time, end_time=end_time)
		# Create a second closure time 4 days later
		ClosureTime.objects.create(
			closure=closure_multiple_times,
			start_time=start_time + timedelta(days=4),
			end_time=end_time + timedelta(days=4),
		)
		do_create_closure_alerts()
		# Both alerts should have been created
		alert_qs = Alert.objects.filter(title=closure_multiple_times.name).order_by("debut_time")
		self.assertEqual(alert_qs.count(), 2)
		alert1 = alert_qs.first()
		self.assertEqual(alert1.title, closure_multiple_times.name)
		self.assertEqual(alert1.debut_time, start_time - timedelta(days=1))
		self.assertEqual(alert1.expiration_time, end_time)
		alert2 = alert_qs.last()
		self.assertEqual(alert2.title, closure_multiple_times.name)
		self.assertEqual(alert2.debut_time, start_time - timedelta(days=1) + timedelta(days=4))
		self.assertEqual(alert2.expiration_time, end_time + timedelta(days=4))

	def testLastClosureEmailNotSent(self):
		# first closure time ends today, but we have one more occurrence later. no email should be sent
		closure = Closure.objects.create(
			name="Closure", alert_days_before=1, alert_template="test", notify_managers_last_occurrence=True
		)
		start_time = timezone.now() - timedelta(days=2)
		end_time = timezone.now()
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		# Create a second closure time 4 days later
		ClosureTime.objects.create(
			closure=closure, start_time=start_time + timedelta(days=4), end_time=end_time + timedelta(days=4)
		)
		do_create_closure_alerts()
		self.assertFalse(
			EmailLog.objects.filter(category=EmailCategory.SYSTEM, subject=f"Last {closure.name} occurrence").exists()
		)

	def testLastClosureEmailSent(self):
		# first closure time ends earlier, last one ends today. email should be sent
		closure = Closure.objects.create(
			name="Closure", alert_days_before=1, alert_template="test", notify_managers_last_occurrence=False
		)
		start_time = timezone.now() - timedelta(weeks=2)
		end_time = timezone.now() - timedelta(weeks=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		# Create a second closure time ending today
		ClosureTime.objects.create(
			closure=closure, start_time=timezone.now() - timedelta(days=1), end_time=timezone.now()
		)
		do_create_closure_alerts()
		# Flag not set on closure so no email
		self.assertFalse(
			EmailLog.objects.filter(category=EmailCategory.SYSTEM, subject=f"Last {closure.name} occurrence").exists()
		)
		closure.notify_managers_last_occurrence = True
		closure.save()
		do_create_closure_alerts()
		# Now email sent
		self.assertTrue(
			EmailLog.objects.filter(category=EmailCategory.SYSTEM, subject=f"Last {closure.name} occurrence").exists()
		)

	def testLastClosureLaterNoEmailSent(self):
		# first closure time ends earlier, last one ends tomorrow. email should not be sent
		closure = Closure.objects.create(
			name="Closure", alert_days_before=1, alert_template="test", notify_managers_last_occurrence=True
		)
		start_time = timezone.now() - timedelta(weeks=2)
		end_time = timezone.now() - timedelta(weeks=1)
		ClosureTime.objects.create(closure=closure, start_time=start_time, end_time=end_time)
		# Create a second closure time ending tomorrow
		ClosureTime.objects.create(
			closure=closure, start_time=timezone.now() - timedelta(days=1), end_time=timezone.now() + timedelta(days=1)
		)
		do_create_closure_alerts()
		self.assertFalse(
			EmailLog.objects.filter(category=EmailCategory.SYSTEM, subject=f"Last {closure.name} occurrence").exists()
		)
