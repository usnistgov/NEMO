from django.urls import path

from NEMO.apps.contracts.views import contracts

urlpatterns = [
    # Contracts and procurements
    path("service_contracts/", contracts.service_contracts, name="service_contracts"),
    path("service_contracts/<int:service_contract_id>/renew/", contracts.service_contract_renew, name="service_contract_renew"),
    path("procurements/", contracts.procurements, name="procurements"),
    path("contractors/", contracts.contractors, name="contractor_agreements"),
    path("contractors/<int:contractor_agreement_id>/renew/", contracts.contractor_agreement_renew, name="contractor_agreement_renew"),
    # Reminders and periodic events
    path("email_contract_reminders/", contracts.email_contract_reminders, name="email_contract_reminders"),
]
