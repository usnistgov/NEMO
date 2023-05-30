import datetime

from dateutil.relativedelta import relativedelta
from django.test import TestCase

from NEMO.apps.contracts.models import ServiceContract


class ContractsAndProcurementsTestCase(TestCase):

	def test_service_contract_year_and_renewal(self):
		service_contract = ServiceContract()
		service_contract.name = "Test service contract"
		service_contract.award_date = datetime.date.today() - relativedelta(years=1) + relativedelta(days=1)
		service_contract.years = 10
		self.assertEqual(service_contract.current_year, 1)
		service_contract.award_date = datetime.date.today() - relativedelta(years=1)
		self.assertEqual(service_contract.current_year, 2)
		self.assertEqual(service_contract.renewal_date, datetime.date.today() + relativedelta(years=9))
		service_contract.award_date = datetime.date.today() - relativedelta(years=1, days=1)
		self.assertEqual(service_contract.current_year, 2)
		self.assertEqual(service_contract.renewal_date, datetime.date.today() - relativedelta(days=1) + relativedelta(years=9))
