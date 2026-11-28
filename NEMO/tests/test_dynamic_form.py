import json
import re
from urllib.parse import parse_qs, urlsplit

from django.http import QueryDict
from django.test import TestCase

from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import Tool
from NEMO.tests.test_utilities import NEMOTestCaseMixin
from NEMO.utilities import EmptyHttpRequest
from NEMO.widgets.dynamic_form import (
    DynamicForm,
    MultiDynamicForms,
    PostUsageGroupQuestion,
    render_group_questions,
)


class TestDynamicForm(NEMOTestCaseMixin, TestCase):

    def setUp(self):
        self.tool = Tool.objects.create()

    def test_editable_fields_treat_unlisted_questions_as_readonly(self):
        questions = [
            {"name": "text", "type": "textbox", "title": "Text"},
            {"name": "number", "type": "number", "title": "Number"},
        ]
        questions_json = json.dumps(questions)

        default_form = DynamicForm(questions_json)
        self.assertNotIn("readonly", default_form.render(self.tool, "pre_usage_question"))

        restricted_form = DynamicForm(questions_json, editable_fields=[])
        rendered = restricted_form.render(self.tool, "pre_usage_question")
        self.assertEqual(rendered.count("readonly"), 2)

    def test_editable_fields_respect_list_and_existing_readonly(self):
        questions = [
            {"name": "editable", "type": "textbox", "title": "Editable"},
            {"name": "restricted", "type": "textbox", "title": "Restricted"},
            {"name": "readonly", "type": "textbox", "title": "Readonly", "readonly": True},
        ]
        form = DynamicForm(json.dumps(questions), editable_fields=["editable", "readonly"])

        rendered = [question.render(False, self.tool, "pre_usage_question") for question in form.questions]
        self.assertNotIn("readonly", rendered[0])
        self.assertIn("readonly", rendered[1])
        self.assertIn("readonly", rendered[2])

    def test_readonly_fields_override_editable_fields(self):
        questions = [
            {"name": "editable", "type": "textbox", "title": "Editable"},
            {"name": "restricted", "type": "textbox", "title": "Restricted"},
            {"name": "configured_readonly", "type": "textbox", "title": "Configured", "readonly": True},
        ]
        form = DynamicForm(
            json.dumps(questions),
            editable_fields=["editable", "restricted", "configured_readonly"],
            readonly_fields=["restricted"],
        )

        rendered = [question.render(False, self.tool, "pre_usage_question") for question in form.questions]
        self.assertNotIn("readonly", rendered[0])
        self.assertIn("readonly", rendered[1])
        self.assertIn("readonly", rendered[2])

        readonly_only_form = DynamicForm(json.dumps(questions), readonly_fields=["restricted"])
        readonly_only_rendered = [
            question.render(False, self.tool, "pre_usage_question") for question in readonly_only_form.questions
        ]
        self.assertNotIn("readonly", readonly_only_rendered[0])
        self.assertIn("readonly", readonly_only_rendered[1])

    def test_temporary_readonly_is_saved_separately_and_cleared_on_reconstruction(self):
        questions = [
            {"name": "editable", "type": "textbox", "title": "Editable"},
            {"name": "allow_listed_out", "type": "textbox", "title": "Allow listed out"},
            {"name": "denied", "type": "textbox", "title": "Denied"},
            {"name": "configured_readonly", "type": "textbox", "title": "Configured", "readonly": True},
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 2,
                "questions": [
                    {"name": "group_editable", "type": "textbox", "title": "Group editable"},
                    {"name": "group_allow_listed_out", "type": "textbox", "title": "Group allow listed out"},
                    {"name": "group_denied", "type": "textbox", "title": "Group denied"},
                    {
                        "name": "group_configured_readonly",
                        "type": "textbox",
                        "title": "Group configured",
                        "readonly": True,
                    },
                ],
            },
        ]
        form = DynamicForm(
            json.dumps(questions),
            editable_fields=["editable", "configured_readonly", "group_editable"],
            readonly_fields=["denied", "configured_readonly", "group_denied", "group_configured_readonly"],
        )

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        result = json.loads(form.extract(request))

        self.assertNotIn("temporarily_readonly", result["editable"])
        self.assertTrue(result["allow_listed_out"]["temporarily_readonly"])
        self.assertNotIn("readonly", result["allow_listed_out"])
        self.assertTrue(result["denied"]["temporarily_readonly"])
        self.assertNotIn("readonly", result["denied"])
        self.assertTrue(result["configured_readonly"]["readonly"])
        self.assertNotIn("temporarily_readonly", result["configured_readonly"])

        group_questions = {question["name"]: question for question in result["group"]["questions"]}
        self.assertNotIn("temporarily_readonly", group_questions["group_editable"])
        self.assertTrue(group_questions["group_allow_listed_out"]["temporarily_readonly"])
        self.assertTrue(group_questions["group_denied"]["temporarily_readonly"])
        self.assertTrue(group_questions["group_configured_readonly"]["readonly"])
        self.assertNotIn("temporarily_readonly", group_questions["group_configured_readonly"])

        reconstructed_form = DynamicForm(json.dumps([result["allow_listed_out"], result["group"]]))
        self.assertFalse(reconstructed_form.questions[0].readonly)
        self.assertNotIn("temporarily_readonly", reconstructed_form.untreated_questions[0])
        reconstructed_sub_questions = {
            question.name: question for question in reconstructed_form.questions[1].sub_questions
        }
        self.assertFalse(reconstructed_sub_questions["group_allow_listed_out"].readonly)
        self.assertTrue(reconstructed_sub_questions["group_configured_readonly"].readonly)

    def test_readonly_choice_questions_remain_submittable(self):
        questions = [
            {
                "name": "checkbox",
                "type": "checkbox",
                "title": "Checkbox",
                "choices": ["first", "second", "third"],
                "default_value": ["first", "third"],
                "required": True,
            },
            {
                "name": "radio",
                "type": "radio",
                "title": "Radio",
                "choices": ["first", "second"],
                "default_value": "second",
                "required": True,
            },
            {
                "name": "select",
                "type": "dropdown",
                "title": "Select",
                "choices": ["first", "second"],
                "default_value": "second",
                "required": True,
            },
        ]
        form = DynamicForm(json.dumps(questions), readonly_fields=["checkbox", "radio", "select"])
        rendered = {
            question.name: question.render(False, self.tool, "pre_usage_question") for question in form.questions
        }

        self.assertNotIn('id="required_df_checkbox"', rendered["checkbox"])
        for choice, should_be_checked in [("first", True), ("second", False), ("third", True)]:
            checkbox = re.search(
                rf'<input type="checkbox" name="df_checkbox" value="{choice}"[^>]*>', rendered["checkbox"]
            ).group(0)
            self.assertIn("disabled", checkbox)
            self.assertEqual("checked" in checkbox, should_be_checked)
        hidden_values = re.findall(
            r'<input type="hidden" name="df_checkbox" value="([^"]*)"[^>]*>', rendered["checkbox"]
        )
        self.assertEqual(hidden_values, ["first", "third"])

        radio = re.search(r'<input type="radio" name="df_radio" value="second"[^>]*>', rendered["radio"]).group(0)
        self.assertIn("disabled", radio)
        self.assertNotIn("aria-readonly", radio)
        self.assertNotIn("onclick", radio)
        self.assertIn("checked", radio)
        self.assertNotIn("required", radio)
        self.assertIn('<input type="hidden" name="df_radio" value="second">', rendered["radio"])

        select = re.search(r"<select[^>]*>", rendered["select"]).group(0)
        selected_option = re.search(r'<option value="second"[^>]*>', rendered["select"]).group(0)
        self.assertIn("disabled", select)
        self.assertNotIn("aria-readonly", select)
        self.assertNotIn("onclick", select)
        self.assertNotIn("required", select)
        self.assertIn("selected", selected_option)
        self.assertIn('<input type="hidden" name="df_select" value="second">', rendered["select"])

        editable_form = DynamicForm(json.dumps(questions))
        editable = {
            question.name: question.render(False, self.tool, "pre_usage_question")
            for question in editable_form.questions
        }
        checkbox = re.search(r'<input type="checkbox" name="df_checkbox"[^>]*>', editable["checkbox"]).group(0)
        checkbox_helper = re.search(r'<input[^>]*id="required_df_checkbox"[^>]*>', editable["checkbox"]).group(0)
        radio = re.search(r'<input type="radio" name="df_radio"[^>]*>', editable["radio"]).group(0)
        self.assertNotIn("disabled", checkbox)
        self.assertNotIn("aria-readonly", checkbox)
        self.assertRegex(checkbox_helper, r"\srequired(?:\s|/|>)")
        self.assertNotIn("disabled", radio)
        self.assertNotIn("aria-readonly", radio)
        self.assertRegex(radio, r"\srequired(?:\s|/|>)")
        select = re.search(r"<select[^>]*>", editable["select"]).group(0)
        self.assertNotIn("disabled", select)
        self.assertRegex(select, r"\srequired(?:\s|/|>)")
        self.assertNotIn('type="hidden" name="df_radio"', editable["radio"])
        self.assertNotIn('type="hidden" name="df_select"', editable["select"])

        request = EmptyHttpRequest()
        request.POST = QueryDict("df_checkbox=first&df_checkbox=third&df_radio=second&df_select=second")
        result = json.loads(form.extract(request))
        self.assertEqual(result["checkbox"]["user_input"], ["first", "third"])
        self.assertEqual(result["radio"]["user_input"], "second")
        self.assertEqual(result["select"]["user_input"], "second")

        empty_request = EmptyHttpRequest()
        empty_request.POST = QueryDict("")
        self.assertIn("checkbox", json.loads(form.extract(empty_request)))

        editable_checkbox_form = DynamicForm(json.dumps([questions[0]]))
        with self.assertRaises(RequiredUnansweredQuestionsException):
            editable_checkbox_form.extract(empty_request)

    def test_readonly_required_questions_are_optional_but_editable_required_questions_are_not(self):
        questions = [{"name": "text", "type": "textbox", "title": "Text", "required": True}]
        readonly_form = DynamicForm(json.dumps(questions), readonly_fields=["text"])
        self.assertTrue(readonly_form.questions[0].required)
        self.assertFalse(readonly_form.questions[0].is_required)

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        self.assertIn("text", json.loads(readonly_form.extract(request)))

        editable_form = DynamicForm(json.dumps(questions))
        with self.assertRaises(RequiredUnansweredQuestionsException):
            editable_form.extract(request)

    def test_readonly_radio_and_dropdown_without_valid_selections_have_no_hidden_values(self):
        questions = [
            {"name": "radio", "type": "radio", "title": "Radio", "choices": ["first", "second"]},
            {
                "name": "select",
                "type": "dropdown",
                "title": "Select",
                "choices": ["first", "second"],
                "default_value": "not-a-choice",
            },
        ]
        form = DynamicForm(json.dumps(questions), readonly_fields=["radio", "select"])
        rendered = {
            question.name: question.render(False, self.tool, "pre_usage_question") for question in form.questions
        }

        for field_name in ("radio", "select"):
            self.assertNotIn(f'type="hidden" name="df_{field_name}"', rendered[field_name])
        self.assertNotIn("checked", rendered["radio"])
        self.assertNotIn('selected" value="first"', rendered["select"])

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        result = json.loads(form.extract(request))
        self.assertNotIn("user_input", result["radio"])
        self.assertNotIn("user_input", result["select"])

    def test_readonly_required_rating_is_optional_but_editable_rating_is_not(self):
        questions = [{"name": "rating", "type": "rating", "title": "Rating", "required": True}]
        initial_data = {"rating": {"type": "rating", "user_input": "3"}}
        readonly_form = DynamicForm(json.dumps(questions), initial_data, readonly_fields=["rating"])
        rendered = readonly_form.questions[0].render(False, self.tool, "pre_usage_question")
        rating_input = re.search(r'<input aria-label="rating value"[^>]*>', rendered).group(0)
        self.assertNotIn("required", rating_input)
        self.assertIn("readonly", rating_input)
        self.assertIn('value="3"', rating_input)
        self.assertNotIn("required-question-star", rendered)
        self.assertNotIn("stars.on('click'", rendered)
        self.assertNotIn("stars.on('mouseenter'", rendered)
        self.assertNotIn("cursor:pointer", rendered)

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        self.assertIn("rating", json.loads(readonly_form.extract(request)))
        request.POST = QueryDict("df_rating=3")
        self.assertEqual(json.loads(readonly_form.extract(request))["rating"]["user_input"], "3")

        editable_form = DynamicForm(json.dumps(questions))
        editable_rendered = editable_form.questions[0].render(False, self.tool, "pre_usage_question")
        editable_input = re.search(r'<input aria-label="rating value"[^>]*>', editable_rendered).group(0)
        self.assertIn("required", editable_input)
        self.assertNotIn("readonly", editable_input)
        self.assertIn("stars.on('click'", editable_rendered)
        self.assertIn("stars.on('mouseenter'", editable_rendered)
        request.POST = QueryDict("")
        with self.assertRaises(RequiredUnansweredQuestionsException):
            editable_form.extract(request)

    def test_readonly_rating_submits_initial_values_for_indexed_group_rows(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 2,
                "questions": [{"name": "rating", "type": "rating", "title": "Rating"}],
            }
        ]
        initial_data = {
            "group": {
                "type": "group",
                "user_input": {"0": {"rating": "2"}, "1": {"rating": "4"}},
            }
        }
        form = DynamicForm(json.dumps(questions), initial_data, readonly_fields=["rating"])
        rendered = form.render(self.tool, "pre_usage_question")

        for index, value in enumerate(("2", "4")):
            name = f"df_rating_{index}" if index else "df_rating"
            self.assertRegex(
                rendered,
                rf'<input aria-label="rating value"[^>]*name="{name}"[^>]*readonly[^>]*value="{value}">',
            )
        self.assertNotIn("stars.on('click'", rendered)
        self.assertNotIn("stars.on('mouseenter'", rendered)

        request = EmptyHttpRequest()
        request.POST = QueryDict("df_rating=2&df_rating_1=4")
        extraction_form = DynamicForm(json.dumps(questions), initial_data, readonly_fields=["rating"])
        result = json.loads(extraction_form.extract(request))["group"]["user_input"]
        self.assertEqual(result["0"]["rating"], "2")
        self.assertEqual(result["1"]["rating"], "4")

    def test_readonly_required_group_checkbox_is_optional_and_submits_checked_value(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 1,
                "questions": [
                    {
                        "name": "checkbox",
                        "type": "checkbox",
                        "title": "Checkbox",
                        "choices": ["saved", "other"],
                        "default_value": ["saved"],
                        "required": True,
                    }
                ],
            }
        ]
        readonly_form = DynamicForm(json.dumps(questions), readonly_fields=["checkbox"])
        rendered = readonly_form.render(self.tool, "pre_usage_question")
        checkbox = re.search(r'<input type="checkbox" name="df_checkbox" value="saved"[^>]*>', rendered).group(0)
        self.assertIn("disabled", checkbox)
        self.assertIn('<input type="hidden" name="df_checkbox" value="saved">', rendered)

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        self.assertIn("group", json.loads(readonly_form.extract(request)))

        request.POST = QueryDict("df_checkbox=saved")
        result = json.loads(readonly_form.extract(request))
        self.assertEqual(result["group"]["user_input"]["0"]["checkbox"], ["saved"])

        editable_form = DynamicForm(json.dumps(questions))
        request.POST = QueryDict("")
        with self.assertRaises(RequiredUnansweredQuestionsException):
            editable_form.extract(request)

    def test_readonly_radio_and_dropdown_submit_initial_values_for_indexed_group_rows(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 2,
                "questions": [
                    {"name": "radio", "type": "radio", "title": "Radio", "choices": ["first", "second"]},
                    {
                        "name": "select",
                        "type": "dropdown",
                        "title": "Select",
                        "choices": ["first", "second"],
                    },
                ],
            }
        ]
        initial_data = {
            "group": {
                "type": "group",
                "user_input": {
                    "0": {"radio": "first", "select": "second"},
                    "1": {"radio": "second", "select": "first"},
                },
            }
        }
        form = DynamicForm(json.dumps(questions), initial_data, readonly_fields=["radio", "select"])
        rendered = form.render(self.tool, "pre_usage_question")

        for field_name, values in (("radio", ("first", "second")), ("select", ("second", "first"))):
            for index, value in enumerate(values):
                input_name = f"df_{field_name}_{index}" if index else f"df_{field_name}"
                self.assertIn(f'<input type="hidden" name="{input_name}" value="{value}">', rendered)

        request = EmptyHttpRequest()
        request.POST = QueryDict("df_radio=first&df_select=second&df_radio_1=second&df_select_1=first")
        extraction_form = DynamicForm(json.dumps(questions), initial_data, readonly_fields=["radio", "select"])
        result = json.loads(extraction_form.extract(request))["group"]["user_input"]
        self.assertEqual(result["0"]["radio"], "first")
        self.assertEqual(result["0"]["select"], "second")
        self.assertEqual(result["1"]["radio"], "second")
        self.assertEqual(result["1"]["select"], "first")

    def test_editable_fields_group_applies_to_group_and_existing_rows(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 3,
                "questions": [
                    {"name": "child", "type": "textbox", "title": "Child"},
                    {"name": "other", "type": "textbox", "title": "Other"},
                    {"name": "locked", "type": "textbox", "title": "Locked", "readonly": True},
                ],
            }
        ]
        initial_data = {
            "group": {
                "type": "group",
                "user_input": {
                    "0": {"child": "first", "locked": "saved"},
                    "1": {"child": "second", "locked": "saved too"},
                },
            }
        }

        restricted_form = DynamicForm(json.dumps(questions), initial_data, editable_fields=[])
        restricted_render = restricted_form.render(self.tool, "pre_usage_question")
        self.assertEqual(restricted_render.count("readonly"), 6)
        self.assertNotIn('class="group_add_button"', restricted_render)
        self.assertNotIn('onclick="remove_group_question', restricted_render)

        child_only_form = DynamicForm(json.dumps(questions), initial_data, editable_fields=["child"])
        child_only_render = child_only_form.render(self.tool, "pre_usage_question")
        self.assertEqual(child_only_render.count("readonly"), 4)
        self.assertIn('class="group_add_button"', child_only_render)
        self.assertIn('onclick="remove_group_question', child_only_render)

        group_only_form = DynamicForm(json.dumps(questions), editable_fields=["group"])
        group_only_render = group_only_form.render(self.tool, "pre_usage_question")
        self.assertIn('class="group_add_button"', group_only_render)
        self.assertEqual(group_only_render.count("readonly"), 1)

        editable_form = DynamicForm(json.dumps(questions), editable_fields=["group", "child"])
        editable_render = editable_form.render(self.tool, "pre_usage_question")
        self.assertIn('class="group_add_button"', editable_render)
        self.assertEqual(editable_render.count("readonly"), 2)

        editable_rows_form = DynamicForm(json.dumps(questions), initial_data, editable_fields=["group", "child"])
        editable_rows_render = editable_rows_form.render(self.tool, "pre_usage_question")
        self.assertEqual(editable_rows_render.count("readonly"), 4)
        self.assertIn('onclick="remove_group_question', editable_rows_render)

    def test_readonly_fields_can_lock_group_or_individual_children(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 3,
                "questions": [
                    {"name": "child", "type": "textbox", "title": "Child"},
                    {"name": "other", "type": "textbox", "title": "Other"},
                ],
            }
        ]

        child_locked_form = DynamicForm(json.dumps(questions), editable_fields=["group"], readonly_fields=["child"])
        child_locked_render = child_locked_form.render(self.tool, "pre_usage_question")
        child_element = re.search(r'<input[^>]*name="df_child"[^>]*>', child_locked_render).group(0)
        other_element = re.search(r'<input[^>]*name="df_other"[^>]*>', child_locked_render).group(0)
        self.assertIn("readonly", child_element)
        self.assertNotIn("readonly", other_element)
        self.assertIn('class="group_add_button"', child_locked_render)

        initial_data = {
            "group": {
                "type": "group",
                "user_input": {
                    "0": {"child": "first", "other": "one"},
                    "1": {"child": "second", "other": "two"},
                },
            }
        }
        group_locked_form = DynamicForm(
            json.dumps(questions), initial_data, editable_fields=["group"], readonly_fields=["group"]
        )
        group_locked_render = group_locked_form.render(self.tool, "pre_usage_question")
        self.assertEqual(group_locked_render.count("readonly"), 4)
        self.assertNotIn('class="group_add_button"', group_locked_render)
        self.assertNotIn('onclick="remove_group_question', group_locked_render)

    def test_formula_only_editable_group_hides_add_and_remove_buttons(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 3,
                "questions": [
                    {"name": "value", "type": "number", "title": "Value"},
                    {"name": "total", "type": "formula", "title": "Total", "formula": "value*2"},
                ],
            }
        ]
        initial_data = {
            "group": {
                "type": "group",
                "user_input": {
                    "0": {"value": "2", "total": "4"},
                    "1": {"value": "3", "total": "6"},
                },
            }
        }

        form = DynamicForm(json.dumps(questions), initial_data, editable_fields=["total"])
        rendered = form.render(self.tool, "pre_usage_question")

        self.assertIn("readonly", rendered)
        self.assertNotIn('class="group_add_button"', rendered)
        self.assertNotIn('onclick="remove_group_question', rendered)

    def test_readonly_group_shows_buttons_when_a_child_is_editable(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "readonly": True,
                "max_number": 3,
                "questions": [{"name": "child", "type": "textbox", "title": "Child"}],
            }
        ]
        initial_data = {
            "group": {
                "type": "group",
                "user_input": {
                    "0": {"child": "first"},
                    "1": {"child": "second"},
                },
            }
        }

        form = DynamicForm(json.dumps(questions), initial_data)
        rendered = form.render(self.tool, "pre_usage_question")

        self.assertIn('class="group_add_button"', rendered)
        self.assertIn('onclick="remove_group_question', rendered)

    def test_editable_fields_are_applied_to_new_group_rows(self):
        questions = [
            {
                "name": "group",
                "type": "group",
                "title": "Group",
                "max_number": 3,
                "questions": [
                    {"name": "child", "type": "textbox", "title": "Child"},
                    {"name": "other", "type": "textbox", "title": "Other"},
                    {"name": "locked", "type": "textbox", "title": "Locked", "readonly": True},
                ],
            }
        ]
        self.tool.pre_usage_question = json.dumps(questions)
        form = DynamicForm(
            self.tool.pre_usage_question,
            editable_fields=["group"],
            readonly_fields=["other"],
        )
        rendered = form.render(self.tool, "pre_usage_question")
        add_button_url = re.search(r"add_group_question\(this, 'group', 3, '([^']+)'\)", rendered).group(1)
        query = parse_qs(urlsplit(add_button_url).query)
        self.assertEqual(json.loads(query["editable_fields"][0]), ["group"])
        self.assertEqual(json.loads(query["readonly_fields"][0]), ["other"])

        request = EmptyHttpRequest()
        request.GET = QueryDict("", mutable=True)
        request.GET.update(
            {
                "index": "1",
                "virtual_inputs": "False",
                "editable_fields": query["editable_fields"][0],
                "readonly_fields": query["readonly_fields"][0],
            }
        )
        new_row = render_group_questions(request, self.tool, "pre_usage_question", "group")
        self.assertEqual(new_row.count("readonly"), 2)
        child_element = re.search(r'<input[^>]*name="df_child_1"[^>]*>', new_row).group(0)
        other_element = re.search(r'<input[^>]*name="df_other_1"[^>]*>', new_row).group(0)
        self.assertNotIn("readonly", child_element)
        self.assertIn("readonly", other_element)

        request.GET.pop("editable_fields")
        request.GET.pop("readonly_fields")
        unrestricted_new_row = render_group_questions(request, self.tool, "pre_usage_question", "group")
        self.assertEqual(unrestricted_new_row.count("readonly"), 1)

    def test_readonly_values_are_extracted_and_used_by_formulas(self):
        questions = [
            {"name": "saved", "type": "number", "title": "Saved", "readonly": True},
            {"name": "extra", "type": "number", "title": "Extra"},
            {"name": "total", "type": "formula", "title": "Total", "formula": "saved+extra"},
        ]
        request = EmptyHttpRequest()
        request.POST = QueryDict("df_saved=3&df_extra=2")
        form = DynamicForm(json.dumps(questions), editable_fields=["extra", "total"])

        result = json.loads(form.extract(request))
        self.assertEqual(result["saved"]["user_input"], "3")
        self.assertEqual(result["total"]["user_input"], "5")

    def test_multi_dynamic_forms_passes_editable_fields_to_rendered_forms(self):
        self.tool.pre_usage_question = json.dumps(
            [{"name": "text", "type": "textbox", "title": "Text", "required": True}]
        )
        forms = MultiDynamicForms([self.tool], "pre_usage_question", editable_fields=[])

        rendered = forms.render()
        self.assertIn("readonly", rendered)
        self.assertTrue(forms.merged_dynamic_forms.questions[0].readonly)
        self.assertTrue(forms.merged_dynamic_forms.questions[0].required)
        self.assertFalse(forms.merged_dynamic_forms.questions[0].is_required)

        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        result = json.loads(forms.extract(request))
        self.assertIn("text", result)
        self.assertTrue(result["text"]["temporarily_readonly"])
        self.assertNotIn("readonly", result["text"])

    def test_multi_dynamic_forms_passes_readonly_fields_to_rendered_forms(self):
        self.tool.pre_usage_question = json.dumps(
            [{"name": "text", "type": "textbox", "title": "Text", "required": True}]
        )
        forms = MultiDynamicForms([self.tool], "pre_usage_question", readonly_fields=["text"])

        rendered = forms.render()
        self.assertIn("readonly", rendered)
        self.assertTrue(forms.merged_dynamic_forms.questions[0].readonly)
        request = EmptyHttpRequest()
        request.POST = QueryDict("")
        result = json.loads(forms.extract(request))
        self.assertTrue(result["text"]["temporarily_readonly"])
        self.assertNotIn("readonly", result["text"])

    def test_question_with_initial_data(self):
        # question and initial data
        initial_data = {"test": {"type": "number", "user_input": "2"}}
        data = [
            {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
        ]
        data_with_default = [
            {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250, "default_value": "1"},
        ]

        # question with initial and no default => initial
        dynamic_form = DynamicForm(json.dumps(data), initial_data=initial_data)
        dynamic_form.validate(self.tool, "pre_usage_question")
        question = [question for question in dynamic_form.questions if question.name == "test"][0]
        self.assertEqual(question.get_default_value(), initial_data["test"]["user_input"])

        # question with no initial data at all => None
        dynamic_form = DynamicForm(json.dumps(data), initial_data=None)
        question = [question for question in dynamic_form.questions if question.name == "test"][0]
        self.assertEqual(question.get_default_value(), None)

        # question with no initial data but default in question => default
        dynamic_form = DynamicForm(json.dumps(data_with_default))
        question = [question for question in dynamic_form.questions if question.name == "test"][0]
        self.assertEqual(question.get_default_value(), data_with_default[0]["default_value"])

        # question with initial data and default in question => initial
        dynamic_form = DynamicForm(json.dumps(data_with_default))
        question = [question for question in dynamic_form.questions if question.name == "test"][0]
        self.assertEqual(question.get_default_value(), data_with_default[0]["default_value"])

        # question with group questions
        group_user_input = {
            "test_group": {
                "type": "group",
                "user_input": {
                    "0": {
                        "test": "2",
                    },
                    "1": {
                        "test": "3",
                    },
                },
            }
        }
        group_data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                ],
            }
        ]
        dynamic_form = DynamicForm(json.dumps(group_data), initial_data=group_user_input)
        question: PostUsageGroupQuestion = [
            question for question in dynamic_form.questions if question.name == "test_group"
        ][0]
        for index, data in enumerate(list(group_user_input["test_group"]["user_input"].values())):
            question.load_sub_questions(index, data)
            sub_question = [question for question in question.sub_questions if question.initial_name == "test"][0]
            self.assertEqual(
                sub_question.get_default_value(), group_user_input["test_group"]["user_input"][str(index)]["test"]
            )

    def test_formula_number_field(self):
        data = [
            {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
            {
                "name": "test_func",
                "type": "formula",
                "title": "test function",
                "formula": "test*2",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        http_request.POST["df_test"] = "2"
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_func"]["user_input"], str(2 * 2))

    def test_formula_float_field(self):
        data = [
            {"name": "test", "type": "float", "title": "Pair of wafer trays", "max-width": 250},
            {
                "name": "test_func",
                "type": "formula",
                "title": "test function",
                "formula": "test*2",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        http_request.POST["df_test"] = "2.0"
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_func"]["user_input"], str(2.0 * 2))

    def test_formula_zero(self):
        data = [
            {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
            {
                "name": "test_func",
                "type": "formula",
                "title": "test function",
                "formula": "test*0",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        http_request.POST["df_test"] = "2"
        extracted_value = json.loads(dynamic_form.extract(http_request))

        self.assertEqual(extracted_value["test_func"]["user_input"], str(0))

    def test_formula_zero_zero(self):
        data = [
            {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
            {
                "name": "test_func",
                "type": "formula",
                "title": "test function",
                "formula": "test*0",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        http_request.POST["df_test"] = "0"
        extracted_value = json.loads(dynamic_form.extract(http_request))

        self.assertEqual(extracted_value["test_func"]["user_input"], str(0))

    def test_formula_inside_group(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "test*0",
                    },
                ],
            }
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test"] = "2"
        http_request.POST["df_test_func"] = ""
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], str(0))

    def test_formula_with_no_value(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "test*2",
                    },
                ],
            }
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test"] = ""
        http_request.POST["df_test_func"] = ""
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], None)

    def test_formula_outside_group(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "test*0",
                    },
                ],
            },
            {
                "name": "test_group2",
                "type": "group",
                "title": "This is a test group2",
                "max_number": 2,
                "questions": [
                    {"name": "test2", "type": "number", "title": "Pair of wafer trays2", "max-width": 250},
                    {
                        "name": "test_func2",
                        "type": "formula",
                        "title": "test function2",
                        "formula": "test2*2",
                    },
                ],
            },
            {
                "name": "test_sum",
                "type": "formula",
                "title": "test function",
                "formula": "sum(test)",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test"] = "2"
        http_request.POST["df_test_2"] = "4"
        http_request.POST["df_test_func"] = ""
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], str(0))
        self.assertEqual(extracted_value["test_sum"]["user_input"], str(6))

    def test_formula_outside_group_with_spaces(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test unit", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "df_test_unit*0",
                    },
                ],
            },
            {
                "name": "test_group2",
                "type": "group",
                "title": "This is a test group2",
                "max_number": 2,
                "questions": [
                    {"name": "test2", "type": "number", "title": "Pair of wafer trays2", "max-width": 250},
                    {
                        "name": "test_func2",
                        "type": "formula",
                        "title": "test function2",
                        "formula": "test2*0",
                    },
                ],
            },
            {
                "name": "test_sum",
                "type": "formula",
                "title": "test function",
                "formula": "sum(df_test_unit)",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test_unit"] = "2"
        http_request.POST["df_test_unit_2"] = "4"
        http_request.POST["df_test_func"] = ""
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], str(0))
        self.assertEqual(extracted_value["test_sum"]["user_input"], str(6))

    def test_formula_using_other_formula_with_missing_arg(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "test*2",
                    },
                ],
            },
            {
                "name": "test_group2",
                "type": "group",
                "title": "This is a test group2",
                "max_number": 2,
                "questions": [
                    {"name": "test2", "type": "number", "title": "Pair of wafer trays2", "max-width": 250},
                    {
                        "name": "test_func2",
                        "type": "formula",
                        "title": "test function2",
                        "formula": "test2*4",
                    },
                ],
            },
            {
                "name": "test_sum",
                "type": "formula",
                "title": "test function",
                "formula": "sum(test_func) + sum(test_func2)",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test"] = "2"
        http_request.POST["df_test_2"] = "4"
        http_request.POST["df_test_func"] = ""
        http_request.POST["df_test_func2"] = ""
        http_request.POST["df_test_sum"] = ""
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], str(4))
        self.assertEqual(extracted_value["test_sum"]["user_input"], str(4))

    def test_formula_using_other_formula(self):
        data = [
            {
                "name": "test_group",
                "type": "group",
                "title": "This is a test group",
                "max_number": 2,
                "questions": [
                    {"name": "test", "type": "number", "title": "Pair of wafer trays", "max-width": 250},
                    {
                        "name": "test_func",
                        "type": "formula",
                        "title": "test function",
                        "formula": "test*2",
                    },
                ],
            },
            {
                "name": "test_group2",
                "type": "group",
                "title": "This is a test group2",
                "max_number": 2,
                "questions": [
                    {"name": "test2", "type": "number", "title": "Pair of wafer trays2", "max-width": 250},
                    {
                        "name": "test_func2",
                        "type": "formula",
                        "title": "test function2",
                        "formula": "test2*4",
                    },
                ],
            },
            {
                "name": "test_sum",
                "type": "formula",
                "title": "test function",
                "formula": "sum(test_func) + sum(test_func2)",
            },
        ]
        dynamic_form = DynamicForm(json.dumps(data))
        dynamic_form.validate(self.tool, "pre_usage_question")
        http_request = EmptyHttpRequest()
        http_request.POST = QueryDict(mutable=True)
        # We are simulating what the request data would look like. Formula questions will render a hidden, no value input
        http_request.POST["df_test"] = "2"
        http_request.POST["df_test_2"] = "4"
        http_request.POST["df_test2"] = "3"
        http_request.POST["df_test2_2"] = "6"
        http_request.POST["df_test_func"] = ""
        http_request.POST["df_test_func_2"] = ""
        http_request.POST["df_test_func2"] = ""
        http_request.POST["df_test_func2_2"] = ""
        http_request.POST["df_test_sum"] = ""
        # Total = sum(test_func) + sum(test_func2) = sum(tests[]*2) + sum(test2[]*4)
        # = sum(2*2, 4*2) + sum(3*4, 6*4) = sum(4, 8) + sum(12, 24) = 12 + 36 = 48
        extracted_value = json.loads(dynamic_form.extract(http_request))
        self.assertEqual(extracted_value["test_group"]["user_input"]["0"]["test_func"], str(4))
        self.assertEqual(extracted_value["test_group"]["user_input"]["2"]["test_func"], str(8))
        self.assertEqual(extracted_value["test_group2"]["user_input"]["0"]["test_func2"], str(12))
        self.assertEqual(extracted_value["test_group2"]["user_input"]["2"]["test_func2"], str(24))
        self.assertEqual(extracted_value["test_sum"]["user_input"], str(48))
