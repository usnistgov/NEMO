from django.test import TestCase

from NEMO.exceptions import ProjectChargeException
from NEMO.models import StaffCharge
from NEMO.policy import policy_class as policy
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class StaffChargesTest(NEMOTestCaseMixin, TestCase):
    def test_staff_charges_not_allowed(self):
        customer, customer_project = create_user_and_project()
        staff, staff_project = create_user_and_project(is_staff=True)
        new_staff_charge = StaffCharge()
        new_staff_charge.customer = customer
        new_staff_charge.staff_member = staff
        new_staff_charge.project = customer_project
        # By default, should work
        policy.check_billing_to_project(customer_project, customer, new_staff_charge, new_staff_charge)
        # Stop allowing staff charges, should fail
        customer_project.allow_staff_charges = False
        customer_project.save()
        self.assertRaises(
            ProjectChargeException,
            policy.check_billing_to_project,
            customer_project,
            customer,
            new_staff_charge,
            new_staff_charge,
        )
