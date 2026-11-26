import json
import re
from urllib.parse import parse_qs, urlsplit

from django.http import QueryDict
from django.test import TestCase

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
        rendered = DynamicForm(self.tool.pre_usage_question, editable_fields=["child"]).render(
            self.tool, "pre_usage_question"
        )
        add_button_url = re.search(r"add_group_question\(this, 'group', 3, '([^']+)'\)", rendered).group(1)
        query = parse_qs(urlsplit(add_button_url).query)
        self.assertEqual(json.loads(query["editable_fields"][0]), ["child"])

        request = EmptyHttpRequest()
        request.GET = QueryDict("", mutable=True)
        request.GET.update({"index": "1", "virtual_inputs": "False", "editable_fields": query["editable_fields"][0]})
        new_row = render_group_questions(request, self.tool, "pre_usage_question", "group")
        self.assertEqual(new_row.count("readonly"), 2)
        child_element = re.search(r'<input[^>]*name="df_child_1"[^>]*>', new_row).group(0)
        other_element = re.search(r'<input[^>]*name="df_other_1"[^>]*>', new_row).group(0)
        self.assertNotIn("readonly", child_element)
        self.assertIn("readonly", other_element)

        request.GET.pop("editable_fields")
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
        self.tool.pre_usage_question = json.dumps([{"name": "text", "type": "textbox", "title": "Text"}])
        forms = MultiDynamicForms([self.tool], "pre_usage_question", editable_fields=[])

        rendered = forms.render()
        self.assertIn("readonly", rendered)
        self.assertFalse(forms.merged_dynamic_forms.questions[0].readonly)

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
