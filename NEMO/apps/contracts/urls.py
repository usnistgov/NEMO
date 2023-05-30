from django.urls import path

from NEMO.apps.contracts.views import contracts

urlpatterns = [
	# Contracts and procurements
	path("service_contracts/", contracts.service_contracts, name="service_contracts"),
	path("procurements/", contracts.procurements, name="procurements"),
	path("contractors/", contracts.contractors, name="contractors"),

	# Reminders and periodic events
	path("send_email_contract_reminders/", contracts.email_contract_reminders, name="send_email_contract_reminders"),
]
