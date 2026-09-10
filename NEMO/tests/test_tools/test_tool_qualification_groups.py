from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from NEMO.admin import ToolQualificationGroupAdminForm
from NEMO.models import Tool, ToolQualificationGroup, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.views.users import record_qualifications


def create_tool(name, owner) -> Tool:
    return Tool.objects.create(name=name, primary_owner=owner, _category="Test")


class ToolQualificationGroupModelTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner", first_name="Tool", last_name="Owner")
        self.fridge = create_tool("Fridge", self.owner)
        self.oven = create_tool("Oven", self.owner)
        self.scope = create_tool("Scope", self.owner)

    def test_get_all_tools_flat_group(self):
        group = ToolQualificationGroup.objects.create(name="Fridges")
        group.tools.set([self.fridge])
        self.assertEqual(group.get_all_tools(), {self.fridge})

    def test_get_all_tools_nested_group(self):
        fridges = ToolQualificationGroup.objects.create(name="Fridges")
        fridges.tools.set([self.fridge])
        ovens = ToolQualificationGroup.objects.create(name="Ovens")
        ovens.tools.set([self.oven])
        no_qual_required = ToolQualificationGroup.objects.create(name="NoQualRequired")
        no_qual_required.tools.set([self.scope])
        no_qual_required.tool_groups.set([fridges, ovens])

        self.assertEqual(no_qual_required.get_all_tools(), {self.fridge, self.oven, self.scope})
        # Leaf groups are unaffected by their parent
        self.assertEqual(fridges.get_all_tools(), {self.fridge})

    def test_get_all_tools_diamond_shaped_hierarchy_is_deduplicated(self):
        # common -> {fridge}; left and right both include common; top includes left and right.
        # "fridge" must only be counted once and no infinite loop should occur.
        common = ToolQualificationGroup.objects.create(name="Common")
        common.tools.set([self.fridge])
        left = ToolQualificationGroup.objects.create(name="Left")
        left.tool_groups.set([common])
        right = ToolQualificationGroup.objects.create(name="Right")
        right.tool_groups.set([common])
        top = ToolQualificationGroup.objects.create(name="Top")
        top.tool_groups.set([left, right])

        self.assertEqual(top.get_all_tools(), {self.fridge})

    def test_get_all_sub_group_ids(self):
        fridges = ToolQualificationGroup.objects.create(name="Fridges")
        no_qual_required = ToolQualificationGroup.objects.create(name="NoQualRequired")
        no_qual_required.tool_groups.set([fridges])

        self.assertEqual(no_qual_required.get_all_sub_group_ids(), {fridges.id})
        self.assertEqual(fridges.get_all_sub_group_ids(), set())

    def test_cannot_add_group_to_itself(self):
        group = ToolQualificationGroup.objects.create(name="Fridges")
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                group.tool_groups.add(group)
        # Nothing should have been added
        self.assertEqual(group.tool_groups.count(), 0)

    def test_cannot_create_indirect_cycle(self):
        a = ToolQualificationGroup.objects.create(name="A")
        b = ToolQualificationGroup.objects.create(name="B")
        b.tool_groups.add(a)  # b -> a
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                a.tool_groups.add(b)  # would make a -> b -> a
        # The original, valid relationship must be untouched
        self.assertEqual(set(b.tool_groups.all()), {a})
        self.assertEqual(a.tool_groups.count(), 0)

    def test_cannot_create_cycle_from_reverse_side(self):
        a = ToolQualificationGroup.objects.create(name="A")
        b = ToolQualificationGroup.objects.create(name="B")
        a.tool_groups.add(b)  # a -> b
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                # Adding b as a parent of a (via the reverse accessor) would establish b -> a,
                # which combined with the existing a -> b would create a cycle.
                a.parent_tool_groups.add(b)
        self.assertEqual(set(a.tool_groups.all()), {b})
        self.assertEqual(b.tool_groups.count(), 0)

    def test_unrelated_groups_can_be_nested_without_error(self):
        a = ToolQualificationGroup.objects.create(name="A")
        b = ToolQualificationGroup.objects.create(name="B")
        c = ToolQualificationGroup.objects.create(name="C")
        # This should simply work: c contains b, which contains a. No cycle.
        b.tool_groups.add(a)
        c.tool_groups.add(b)
        self.assertEqual(c.get_all_tools(), set())
        self.assertEqual(c.get_all_sub_group_ids(), {a.id, b.id})


class ToolQualificationGroupAdminFormTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner2", first_name="Tool", last_name="Owner")
        self.tool = create_tool("Microscope", self.owner)
        self.a = ToolQualificationGroup.objects.create(name="A")
        self.a.tools.set([self.tool])
        self.b = ToolQualificationGroup.objects.create(name="B")
        self.b.tool_groups.set([self.a])  # b -> a

    def test_form_rejects_circular_reference(self):
        form = ToolQualificationGroupAdminForm(
            data={"name": "A", "tools": [self.tool.id], "tool_groups": [self.b.id]},
            instance=self.a,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("tool_groups", form.errors)

    def test_form_accepts_valid_hierarchy(self):
        c = ToolQualificationGroup.objects.create(name="C")
        form = ToolQualificationGroupAdminForm(
            data={"name": "B", "tools": [], "tool_groups": [self.a.id, c.id]},
            instance=self.b,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_accepts_new_group_with_no_existing_id_to_conflict_with(self):
        form = ToolQualificationGroupAdminForm(
            data={"name": "Brand new group", "tools": [self.tool.id], "tool_groups": [self.a.id]},
        )
        self.assertTrue(form.is_valid(), form.errors)


class RecordQualificationsTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner3", first_name="Tool", last_name="Owner")
        self.requester = User.objects.create(username="requester", first_name="Req", last_name="Uester")
        self.trainee = User.objects.create(username="trainee", first_name="Train", last_name="Ee")
        self.fridge = create_tool("Fridge3", self.owner)
        self.oven = create_tool("Oven3", self.owner)

    def test_record_qualifications_with_flat_group(self):
        group = ToolQualificationGroup.objects.create(name="FlatGroup")
        group.tools.set([self.fridge, self.oven])

        record_qualifications(self.requester, self.trainee, [], [str(group.id)])

        self.assertEqual(set(self.trainee.qualifications.all()), {self.fridge, self.oven})

    def test_record_qualifications_with_nested_group(self):
        fridges = ToolQualificationGroup.objects.create(name="FridgesNested")
        fridges.tools.set([self.fridge])
        top = ToolQualificationGroup.objects.create(name="TopNested")
        top.tools.set([self.oven])
        top.tool_groups.set([fridges])

        record_qualifications(self.requester, self.trainee, [], [str(top.id)])

        self.assertEqual(set(self.trainee.qualifications.all()), {self.fridge, self.oven})

    def test_record_qualifications_removes_qualifications_not_in_new_set(self):
        group = ToolQualificationGroup.objects.create(name="ReplaceGroup")
        group.tools.set([self.fridge])
        self.trainee.qualifications.add(self.oven)

        record_qualifications(self.requester, self.trainee, [], [str(group.id)])

        self.assertEqual(set(self.trainee.qualifications.all()), {self.fridge})

    def test_record_qualifications_combines_individual_tools_and_groups(self):
        group = ToolQualificationGroup.objects.create(name="CombinedGroup")
        group.tools.set([self.fridge])
        other_tool = create_tool("Standalone", self.owner)

        record_qualifications(self.requester, self.trainee, [str(other_tool.id)], [str(group.id)])

        self.assertEqual(set(self.trainee.qualifications.all()), {self.fridge, other_tool})


class CreateOrModifyUserViewTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.staff = User.objects.create(
            username="admin_user", first_name="Admin", last_name="User", is_staff=True, is_facility_manager=True
        )
        self.trainee = User.objects.create(username="trainee2", first_name="Train", last_name="Ee2")
        self.fridge = create_tool("Fridge4", self.staff)
        self.oven = create_tool("Oven4", self.staff)
        self.group = ToolQualificationGroup.objects.create(name="ViewGroup")
        self.group.tools.set([self.fridge, self.oven])
        self.login_as(self.staff)

    def test_group_appears_in_search_data(self):
        response = self.client.get(reverse("create_or_modify_user", args=[self.trainee.id]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("ViewGroup", content)
        self.assertIn('"toolqualificationgroup"', content.lower())

    def test_post_with_group_qualifies_user_for_all_its_tools(self):
        url = reverse("create_or_modify_user", args=[self.trainee.id])
        response = self.client.get(url)
        content = response.content.decode()
        import re

        csrf_token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', content).group(1)
        post_data = {
            "csrfmiddlewaretoken": csrf_token,
            "username": self.trainee.username,
            "first_name": self.trainee.first_name,
            "last_name": self.trainee.last_name,
            "email": "trainee2@example.com",
            "type": "",
            "domain": "",
            "is_active": "on",
            "tool_qualification_groups": str(self.group.id),
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.trainee.refresh_from_db()
        self.assertEqual(set(self.trainee.qualifications.all()), {self.fridge, self.oven})


class BatchQualificationsTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.owner = User.objects.create(username="owner5", first_name="Tool", last_name="Owner")
        self.owned_tool = create_tool("OwnedTool", self.owner)
        self.other_tool = create_tool("OtherTool", self.owner)
        self.tool_staff = User.objects.create(username="tool_staff_user", first_name="Tool", last_name="Staff")
        self.owned_tool.staff.add(self.tool_staff)
        self.trainee = User.objects.create(username="trainee3", first_name="Train", last_name="Ee3")

    def test_tool_staff_only_sees_groups_fully_within_their_tools(self):
        in_scope = ToolQualificationGroup.objects.create(name="InScopeGroup")
        in_scope.tools.set([self.owned_tool])

        out_of_scope_inner = ToolQualificationGroup.objects.create(name="OutOfScopeInner")
        out_of_scope_inner.tools.set([self.other_tool])
        out_of_scope_outer = ToolQualificationGroup.objects.create(name="OutOfScopeOuter")
        out_of_scope_outer.tools.set([self.owned_tool])
        out_of_scope_outer.tool_groups.set([out_of_scope_inner])

        self.login_as(self.tool_staff)
        response = self.client.get(reverse("qualifications"))
        content = response.content.decode()
        self.assertIn("InScopeGroup", content)
        self.assertNotIn("OutOfScopeOuter", content)

    def test_full_staff_sees_all_groups(self):
        group = ToolQualificationGroup.objects.create(name="AnyGroup")
        group.tools.set([self.other_tool])
        staff = User.objects.create(username="full_staff", first_name="Full", last_name="Staff", is_staff=True)
        self.login_as(staff)
        response = self.client.get(reverse("qualifications"))
        self.assertIn("AnyGroup", response.content.decode())

    def test_modify_qualifications_expands_nested_group(self):
        inner = ToolQualificationGroup.objects.create(name="ModifyInner")
        inner.tools.set([self.other_tool])
        outer = ToolQualificationGroup.objects.create(name="ModifyOuter")
        outer.tools.set([self.owned_tool])
        outer.tool_groups.set([inner])

        staff = User.objects.create(username="modify_staff", first_name="Modify", last_name="Staff", is_staff=True)
        self.login_as(staff)
        response = self.client.post(
            reverse("modify_qualifications"),
            {
                "action": "qualify",
                "chosen_user[]": [str(self.trainee.id)],
                "chosen_toolqualificationgroup[]": [str(outer.id)],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.trainee.qualifications.all()), {self.owned_tool, self.other_tool})
