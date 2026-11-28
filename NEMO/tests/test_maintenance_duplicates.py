from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Task, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin


class MaintenanceDuplicateTaskTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        self.user = User.objects.create(username="duplicate_admin", is_staff=True)
        self.tool = Tool.objects.create(name="Duplicate test tool", _operational=True, _category="Test")
        self.other_tool = Tool.objects.create(name="Other duplicate test tool", _operational=True, _category="Test")
        self.login_as(self.user)

    def create_task(self, tool=None, **kwargs):
        defaults = {
            "tool": tool or self.tool,
            "creator": self.user,
            "urgency": Task.Urgency.NORMAL,
            "force_shutdown": False,
            "safety_hazard": False,
            "problem_description": "A reported problem",
        }
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def post_duplicate(self, task, duplicate_of):
        data = {
            "action": "duplicate",
            "duplicate_of": duplicate_of.pk,
            "tool": task.tool_id,
            "urgency": task.urgency,
            "description": "",
        }
        with (
            patch("NEMO.views.tasks.determine_tool_status"),
            patch("NEMO.views.tasks.send_task_updated_email"),
        ):
            return self.client.post(reverse("update_task", kwargs={"task_id": task.pk}), data)

    def test_multiple_tasks_can_be_marked_as_duplicates(self):
        main_task = self.create_task()
        duplicate_tasks = [self.create_task(), self.create_task()]

        for duplicate in duplicate_tasks:
            response = self.post_duplicate(duplicate, main_task)
            self.assertEqual(response.status_code, 302)

        for duplicate in duplicate_tasks:
            duplicate.refresh_from_db()
            self.assertEqual(duplicate.duplicate_of, main_task)
            self.assertTrue(duplicate.resolved)
            self.assertFalse(duplicate.cancelled)
            self.assertEqual(duplicate.resolver, self.user)
            self.assertLessEqual(duplicate.resolution_time, timezone.now())

    def test_existing_duplicates_follow_task_when_it_becomes_a_duplicate(self):
        main_task = self.create_task()
        task_being_merged = self.create_task()
        existing_duplicate = self.create_task(
            resolved=True, resolution_time=timezone.now(), duplicate_of=task_being_merged
        )

        response = self.post_duplicate(task_being_merged, main_task)

        self.assertEqual(response.status_code, 302)
        existing_duplicate.refresh_from_db()
        self.assertEqual(existing_duplicate.duplicate_of, main_task)

    def test_duplicate_candidates_are_limited_to_other_active_tasks_on_same_tool(self):
        task = self.create_task()
        candidate = self.create_task()
        other_tool_task = self.create_task(tool=self.other_tool)
        closed_task = self.create_task(resolved=True, resolution_time=timezone.now())

        response = self.client.get(reverse("task_details", kwargs={"task_id": task.pk}))

        self.assertContains(response, f"Task #{candidate.pk}")
        self.assertNotContains(response, f"Task #{task.pk}")
        self.assertNotContains(response, f"Task #{other_tool_task.pk}")
        self.assertNotContains(response, f"Task #{closed_task.pk}")

    def test_pending_and_closed_tables_show_task_id_before_urgency(self):
        pending_task = self.create_task()
        closed_task = self.create_task(resolved=True, resolution_time=timezone.now())

        response = self.client.get(reverse("maintenance"))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for table_id, task in (("pending_tasks", pending_task), ("closed_tasks", closed_task)):
            table = content.split(f'<table id="{table_id}"', 1)[1].split("</table>", 1)[0]
            self.assertLess(table.index("ID"), table.index("Urgency"))
            self.assertLess(table.index(f"<td>{task.pk}</td>"), table.index("<td>Normal</td>"))

    def test_duplicate_links_show_titles_or_fall_back_to_unquoted_ids(self):
        main_task = self.create_task(title="Main task <repair>")
        titled_duplicate = self.create_task(
            title="Titled duplicate", resolved=True, resolution_time=timezone.now(), duplicate_of=main_task
        )
        untitled_duplicate = self.create_task(resolved=True, resolution_time=timezone.now(), duplicate_of=main_task)
        escaped_duplicate = self.create_task(
            title="<script>alert('duplicate')</script>",
            resolved=True,
            resolution_time=timezone.now(),
            duplicate_of=main_task,
        )

        pending_details = self.client.get(reverse("task_details", kwargs={"task_id": main_task.pk}))
        self.assertContains(pending_details, f"Titled duplicate (#{titled_duplicate.pk})")
        self.assertContains(pending_details, f"Task #{untitled_duplicate.pk}")
        self.assertContains(
            pending_details,
            f"&lt;script&gt;alert(&#x27;duplicate&#x27;)&lt;/script&gt; (#{escaped_duplicate.pk})",
        )
        self.assertNotContains(pending_details, "<script>alert('duplicate')</script>")
        self.assertContains(pending_details, f"?tab=closed&amp;task_id={titled_duplicate.pk}")

        closed_details = self.client.get(reverse("task_details", kwargs={"task_id": titled_duplicate.pk}))
        self.assertContains(closed_details, f"Main task &lt;repair&gt; (#{main_task.pk})")
        self.assertContains(closed_details, f"?tab=pending&amp;task_id={main_task.pk}")

        untitled_main_task = self.create_task()
        closed_task_without_title = self.create_task(
            resolved=True,
            resolution_time=timezone.now(),
            duplicate_of=untitled_main_task,
        )
        untitled_closed_details = self.client.get(
            reverse("task_details", kwargs={"task_id": closed_task_without_title.pk})
        )
        self.assertContains(untitled_closed_details, f"Task #{untitled_main_task.pk}")

    def test_pending_and_closed_details_link_to_each_other_and_older_closed_tasks(self):
        main_task = self.create_task()
        old_duplicate = self.create_task(
            resolved=True,
            resolution_time=timezone.now() - timedelta(days=100),
            duplicate_of=main_task,
        )
        for index in range(21):
            self.create_task(
                resolved=True,
                resolution_time=timezone.now() - timedelta(days=index + 1),
            )

        pending_details = self.client.get(reverse("task_details", kwargs={"task_id": main_task.pk}))
        self.assertContains(pending_details, f"?tab=closed&amp;task_id={old_duplicate.pk}")

        closed_details = self.client.get(reverse("task_details", kwargs={"task_id": old_duplicate.pk}))
        self.assertContains(closed_details, f"?tab=pending&amp;task_id={main_task.pk}")
        maintenance_response = self.client.get(reverse("maintenance"), {"tab": "closed", "task_id": old_duplicate.pk})
        self.assertEqual(maintenance_response.status_code, 200)
        self.assertEqual(maintenance_response.context["tab"], "closed")
        self.assertNotIn(old_duplicate, maintenance_response.context["closed_tasks"])

    def test_invalid_duplicate_targets_are_rejected(self):
        task = self.create_task()
        other_tool_task = self.create_task(tool=self.other_tool)
        closed_task = self.create_task(resolved=True, resolution_time=timezone.now())

        for invalid_target in (task, other_tool_task, closed_task):
            response = self.post_duplicate(task, invalid_target)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Task update failed")
            task.refresh_from_db()
            self.assertFalse(task.resolved)
            self.assertIsNone(task.duplicate_of)

    def test_closed_task_cannot_be_marked_as_a_duplicate(self):
        task = self.create_task(resolved=True, resolution_time=timezone.now())
        main_task = self.create_task()

        response = self.post_duplicate(task, main_task)

        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertTrue(task.resolved)
        self.assertIsNone(task.duplicate_of)

    def test_reopening_task_clears_duplicate_relationship(self):
        main_task = self.create_task()
        duplicate = self.create_task(resolved=True, resolution_time=timezone.now(), duplicate_of=main_task)
        data = {
            "action": "update",
            "tool": duplicate.tool_id,
            "urgency": duplicate.urgency,
            "description": "Reopened for continued work",
        }
        with (
            patch("NEMO.views.tasks.determine_tool_status"),
            patch("NEMO.views.tasks.send_task_updated_email"),
        ):
            response = self.client.post(reverse("update_task", kwargs={"task_id": duplicate.pk}), data)

        self.assertEqual(response.status_code, 302)
        duplicate.refresh_from_db()
        self.assertFalse(duplicate.resolved)
        self.assertIsNone(duplicate.duplicate_of)

    def test_regular_update_does_not_change_other_task_relationships(self):
        main_task = self.create_task()
        duplicate = self.create_task(resolved=True, resolution_time=timezone.now(), duplicate_of=main_task)
        data = {
            "action": "update",
            "tool": main_task.tool_id,
            "urgency": main_task.urgency,
            "description": "Updated task description",
        }
        with (
            patch("NEMO.views.tasks.determine_tool_status"),
            patch("NEMO.views.tasks.send_task_updated_email"),
        ):
            response = self.client.post(reverse("update_task", kwargs={"task_id": main_task.pk}), data)

        self.assertEqual(response.status_code, 302)
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.duplicate_of, main_task)

    def test_tool_staff_cannot_duplicate_task_for_another_tool(self):
        task = self.create_task()
        main_task = self.create_task()
        self.user.is_staff = False
        self.user.save()
        self.other_tool.staff.add(self.user)

        response = self.post_duplicate(task, main_task)

        self.assertEqual(response.status_code, 400)
        task.refresh_from_db()
        self.assertFalse(task.resolved)
