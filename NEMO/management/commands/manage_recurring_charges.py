from django.core.management import BaseCommand

from NEMO.views.calendar import do_manage_recurring_charges


class Command(BaseCommand):
	help = (
		"Run every day to charge recurring consumable orders."
		"Also sends reminders if set on the recurring consumable charge and the email template is set."
	)

	def handle(self, *args, **options):
		do_manage_recurring_charges()
