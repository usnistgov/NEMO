import sys
from collections import Counter
from copy import copy
from distutils.util import strtobool
from json import dumps, loads
from logging import getLogger
from typing import Any, Callable, Dict, List, Optional, Type

from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

from NEMO.exceptions import RequiredUnansweredQuestionsException
from NEMO.models import Consumable, ToolUsageCounter
from NEMO.utilities import slugify_underscore
from NEMO.views.consumables import make_withdrawal

dynamic_form_logger = getLogger(__name__)


GROUP_TYPE_FIELD_KEY = "group"


class PostUsageQuestion:
    question_type = "Question"

    required_span = '<span style="color:red">*</span>'

    def __init__(self, properties: Dict, index: int = None):
        self.properties = properties
        self.name = self._init_property("name")
        self.title = self._init_property("title")
        self.title_html = self._init_property("title_html")
        self.help = self._init_property("help")
        self.type = self._init_property("type")
        self.max_width = self._init_property("max-width")
        self.maxlength = self._init_property("maxlength")
        self.placeholder = self._init_property("placeholder")
        self.prefix = self._init_property("prefix")
        self.suffix = self._init_property("suffix")
        self.pattern = self._init_property("pattern")
        self.min = self._init_property("min")
        self.max = self._init_property("max")
        self.precision = self._init_property("precision")
        self.step = self._init_property("step")
        self.rows = self._init_property("rows")
        self.consumable = self._init_property("consumable")
        self.required = self._init_property("required", True)
        # For backwards compatibility keep default choice
        self.default_value = self._init_property("default_value") or self._init_property("default_choice")
        self.choices = self._init_property("choices")
        self.labels = self._init_property("labels")
        self.group_add_button_name = self._init_property("group_add_button_name") or "Add"
        self.index = index
        if index and not isinstance(self, PostUsageGroupQuestion):
            self.name = f"{self.name}_{index}"
        # form_name is used in forms and extraction to avoid potential conflicts with other data
        self.form_name = f"df_{self.name}"
        pass

    def _init_property(self, prop: str, boolean: bool = False) -> Any:
        if boolean:
            return True if prop in self.properties and self.properties[prop] is True else False
        else:
            return self.properties[prop] if prop in self.properties else None

    def validate(self):
        self.validate_property_exists("name")
        self.validate_property_exists("title")
        self.validate_property_exists("type")

    def render(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        return self.render_element(virtual_inputs, group_question_url, group_item_id) + self.render_script(
            virtual_inputs, group_question_url, group_item_id
        )

    def render_as_text(self) -> str:
        result = f"{self.title}\n"
        result += "<strong>your answer</strong>"
        if self.choices:
            result += " (possible choices: " + "|".join(self.choices) + ")"
        return result

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        return ""

    def render_script(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        return ""

    def extract(self, request, index=None) -> Dict:
        answered_question = copy(self.properties)
        user_input = request.POST.get(f"{self.form_name}_{index}" if index else self.form_name)
        if user_input:
            answered_question["user_input"] = user_input
        return answered_question

    def validate_property_exists(self, prop: str):
        try:
            self.properties[prop]
        except KeyError:
            raise Exception(f"{self.question_type} requires property '{prop}' to be defined")

    def validate_labels_and_choices(self):
        self.validate_property_exists("choices")
        if "labels" in self.properties:
            if len(self.properties["labels"]) != len(self.properties["choices"]):
                raise Exception("When using labels you need one for each choice")

    @staticmethod
    def load_questions(questions: Optional[List[Dict]], index: int = None):
        questions_to_load = questions or []
        post_usage_questions: List[PostUsageQuestion] = []
        for question in questions_to_load:
            post_usage_questions.append(question_types.get(question["type"], PostUsageQuestion)(question, index))
        return post_usage_questions


class PostUsageRadioQuestion(PostUsageQuestion):
    question_type = "Question of type radio"

    def validate(self):
        super().validate()
        self.validate_labels_and_choices()

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        title = self.title_html or self.title
        result = f'<div class="form-group"><div style="white-space: pre-wrap">{title}{self.required_span if self.required else ""}</div>'
        for index, choice in enumerate(self.choices):
            label = self.labels[index] if self.labels else choice
            result += '<div class="radio">'
            required = "required" if self.required else ""
            is_default_choice = "checked" if self.default_value and self.default_value == choice else ""
            result += f'<label><input type="radio" name="{self.form_name}" value="{choice}" {required} {is_default_choice}>{label}</label>'
            result += "</div>"
        result += "</div>"
        return result


class PostUsageCheckboxQuestion(PostUsageQuestion):
    question_type = "Question of type checkbox"

    def validate(self):
        super().validate()
        self.validate_labels_and_choices()

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        title = self.title_html or self.title
        result = f'<div class="form-group"><div style="white-space: pre-wrap">{title}{self.required_span if self.required else ""}</div>'
        result += f'<input aria-label="hidden field used for required answer" id="required_{ self.form_name }" type="checkbox" value="" style="display: none" { "required" if self.required else "" }/>'
        for index, choice in enumerate(self.choices):
            label = self.labels[index] if self.labels else choice
            result += '<div class="checkbox">'
            required = f"""onclick="checkbox_required('{self.form_name}')" """ if self.required else ""
            is_default_choice = "checked" if self.default_value and self.default_value == choice else ""
            result += f'<label><input type="checkbox" name="{self.form_name}" value="{choice}" {required} {is_default_choice}>{label}</label>'
            result += "</div>"
        result += "</div>"
        return result

    def render_script(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        result = "<script>"
        result += "function checkbox_required(form_name) {"
        result += "if ($('input[name=' + form_name + ']:checkbox:checked').length > 0) {"
        result += "$('#required_' + form_name).prop('checked', true).change();"
        result += "} else {"
        result += "$('#required_'+ form_name).prop('checked', false).change();"
        result += "} }"
        result += "</script>"
        return result

    def extract(self, request, index=None) -> Dict:
        answered_question = copy(self.properties)
        user_input = request.POST.getlist(f"{self.form_name}_{index}" if index else self.form_name)
        if user_input:
            answered_question["user_input"] = user_input
        return answered_question


class PostUsageDropdownQuestion(PostUsageQuestion):
    question_type = "Question of type dropdown"

    def validate(self):
        super().validate()
        self.validate_property_exists("max-width")
        self.validate_labels_and_choices()

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        title = self.title_html or self.title
        max_width = f"max-width:{self.max_width}px"
        result = f'<div class="form-group"><div style="white-space: pre-wrap">{title}{self.required_span if self.required else ""}</div>'
        required = "required" if self.required else ""
        result += (
            f'<select name="{self.form_name}" {required} style="margin-top: 5px;{max_width}" class="form-control">'
        )
        blank_disabled = 'disabled="disabled"' if required else ""
        placeholder = self.placeholder if self.placeholder else "Select an option"
        result += f'<option {blank_disabled} selected="selected" value="">{placeholder}</option>'
        for index, choice in enumerate(self.choices):
            label = self.labels[index] if self.labels else choice
            is_default_choice = "selected" if self.default_value and self.default_value == choice else ""
            result += f'<option value="{choice}" {is_default_choice}>{label}</option>'
        result += "</select>"
        if self.help:
            result += f'<div style="font-size:smaller;color:#999;{max_width}">{self.help}</div>'
        result += "</div>"
        return result


class PostUsageTextFieldQuestion(PostUsageQuestion):
    question_type = "Question of type text"

    def validate(self):
        super().validate()
        self.validate_property_exists("max-width")

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        title = self.title_html or self.title
        max_width = f"max-width:{self.max_width}px"
        result = '<div class="form-group">'
        result += f'<label for="{self.form_name}" style="white-space: pre-wrap">{title}{self.required_span if self.required else ""}</label>'
        input_group_required = True if self.prefix or self.suffix else False
        if input_group_required:
            result += f'<div class="input-group" style="{max_width}">'
        if self.prefix:
            result += f'<span class="input-group-addon">{self.prefix}</span>'
        required = "required" if self.required else ""
        pattern = f'pattern="{self.pattern}"' if self.pattern else ""
        placeholder = f'placeholder="{self.placeholder}"' if self.placeholder else ""
        default_value = f'value="{self.default_value}"' if self.default_value else ""
        result += self.render_input(required, pattern, placeholder, default_value)
        if self.suffix:
            result += f'<span class="input-group-addon">{self.suffix}</span>'
        if input_group_required:
            result += "</div>"
        if self.help:
            result += f'<div style="font-size:smaller;color:#999;{max_width}">{self.help}</div>'
        result += "</div>"
        return result

    def render_input(self, required: str, pattern: str, placeholder: str, default_value: str) -> str:
        maxlength = f'maxlength="{self.maxlength}"' if self.maxlength else ""
        return f'<input type="text" class="form-control" id="{self.form_name}" name="{self.form_name}" {maxlength} {placeholder} {pattern} {default_value} {required} style="max-width:{self.max_width}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'

    def render_script(self, virtual_inputs: bool, group_question_url: str, item_id: int) -> str:
        if virtual_inputs:
            return f"<script>$('#{self.form_name}').keyboard();</script>"
        return super().render_script(virtual_inputs, group_question_url, item_id)

    def render_as_text(self) -> str:
        result = f"{self.title}\n"
        if self.prefix:
            result += self.prefix
        result += "<strong>your answer</strong>"
        if self.suffix:
            result += f" {self.suffix}"
        return result


class PostUsageTextAreaFieldQuestion(PostUsageTextFieldQuestion):
    question_type = "Question of type textarea"

    def render_input(self, required: str, pattern: str, placeholder: str, default_value: str) -> str:
        rows = f'rows="{str(self.rows)}"' if self.rows else ""
        return f'<textarea class="form-control" id="{self.form_name}" name="{self.form_name}" {rows} {placeholder} {required} style="max-width:{self.max_width}px;height:inherit" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">{self.default_value or ""}</textarea>'


class PostUsageNumberFieldQuestion(PostUsageTextFieldQuestion):
    question_type = "Question of type number"

    def render_input(self, required: str, pattern: str, placeholder: str, default_value: str) -> str:
        minimum = f'min="{self.min}"' if self.min else ""
        maximum = f'max="{self.max}"' if self.max else ""
        step = f'step="{self.step}"' if self.step else ""
        return f'<input type="number" class="form-control" id="{self.form_name}" name="{self.form_name}" {placeholder} {pattern} {minimum} {maximum} {default_value} {step} {required} style="max-width:{self.max_width}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'

    def render_script(self, virtual_inputs: bool, group_question_url: str, item_id: int) -> str:
        if virtual_inputs:
            return f"<script>$('#{self.form_name}').numpad({{'readonly': false, 'hidePlusMinusButton': true, 'hideDecimalButton': true}});</script>"
        return super().render_script(virtual_inputs, group_question_url, item_id)

    def render_as_text(self) -> str:
        result = super().render_as_text()
        if self.min or self.max:
            result += " ("
            if self.min:
                result += f"min: {self.min}"
            if self.max:
                if self.min:
                    result += ", "
                result += f"max: {self.min}"
            result += ")"
        return result


class PostUsageFloatFieldQuestion(PostUsageTextFieldQuestion):
    question_type = "Question of type float"

    def render_input(self, required: str, pattern: str, placeholder: str, default_value: str) -> str:
        precision = self.precision if self.precision else 2
        pattern = f'pattern="^\s*(?=.*[0-9])\d*(?:\.\d{"{1," + str(precision) + "}"})?\s*$"'
        return f'<input type="text" class="form-control" id="{self.form_name}" name="{self.form_name}" {placeholder} {pattern} {default_value} {required} style="max-width:{self.max_width}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'

    def render_script(self, virtual_inputs: bool, group_question_url: str, item_id: int) -> str:
        if virtual_inputs:
            return f"<script>$('#{self.form_name}').numpad({{'readonly': false, 'hidePlusMinusButton': true, 'hideDecimalButton': false}});</script>"
        return super().render_script(virtual_inputs, group_question_url, item_id)


class PostUsageGroupQuestion(PostUsageQuestion):
    question_type = "Question of type group"

    def __init__(self, properties: Dict, index: int = None):
        super().__init__(properties, index)
        self.max_number = self._init_property("max_number")
        # we need a safe group name to use in js function and variable names
        self.group_name = slugify_underscore(self.name)
        self.sub_questions: List[PostUsageQuestion] = PostUsageQuestion.load_questions(
            self._init_property("questions"), index
        )

    def validate(self):
        super().validate()
        self.validate_property_exists("questions")
        self.validate_property_exists("max_number")
        for sub_question in self.sub_questions:
            sub_question.validate()

    def render_element(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        title = self.title_html or self.title
        result = f'<div class="form-group"><div style="white-space: pre-wrap">{title}</div></div>'
        result += f'<div id="{self.group_name}_container">'
        result += self.render_group_question(virtual_inputs, group_question_url, group_item_id)
        result += "</div>"
        result += "</div>"
        result += '<div class="form-group">'
        result += f'<button id="{self.group_name}_add_button" type="button" onclick="add_question_{self.group_name}()">{self.group_add_button_name}</button>'
        result += "</div>"
        return result

    def render_group_question(self, virtual_inputs: bool, group_question_url: str, group_item_id: int) -> str:
        result = ""
        result += f'<div class="{self.group_name}_question" style="padding-top: 10px; padding-bottom: 10px; border-top: 1px solid lightgray">'
        for sub_question in self.sub_questions:
            result += sub_question.render(virtual_inputs, group_question_url, group_item_id)
        if self.index:
            result += f'<button type="button" onclick="remove_question_{self.group_name}(this);">Remove</button>'
        return result

    def render_script(self, virtual_inputs: bool, group_question_url: str, item_id: int) -> str:
        return f"""
		<script>
			if (!$) {{ $ = django.jQuery; }}
			var {self.group_name}_question_index=1;
			function update_add_button_{self.group_name}()
			{{
				if ($(".{self.group_name}_question").length < {self.max_number})
				{{
					$("#{self.group_name}_add_button").show();
				}}
				else
				{{
					$("#{self.group_name}_add_button").hide();
				}}
			}};
			function remove_question_{self.group_name}(element)
			{{
				$(element).parents(".{self.group_name}_question").remove();
				$("body").trigger("question-group-changed");
				update_add_button_{self.group_name}();
			}}
			function add_question_{self.group_name}()
			{{
				$.ajax({{ type: "GET", url: "{reverse(group_question_url, args=[item_id, self.group_name])}?virtual_inputs={virtual_inputs}&index="+{self.group_name}_question_index, success : function(response)
				{{
					{self.group_name}_question_index ++;
					$("#{self.group_name}_container").append(response);
					$("body").trigger("question-group-changed");
					update_add_button_{self.group_name}();
				}}
				}});
			}}
		</script>"""

    def render_as_text(self) -> str:
        result = f"{self.title}\n"
        for question in self.sub_questions:
            result += question.render_as_text()
        return result

    def extract(self, request, index=None) -> Dict:
        # For group question, we also have to look for answers submitted
        # with a numbered suffix (i.e. question, question_1, question_2 etc.)
        # The result of the extraction will be a dictionary, with the keys being the group number,
        # and the values the user inputs for all questions of the group.
        sub_results = copy(self.properties)
        user_inputs = {}
        question_form_names = [sub_question.form_name for sub_question in self.sub_questions]
        for key in request.POST.keys():
            if key in question_form_names:
                for sub_question in self.sub_questions:
                    if key == sub_question.form_name:
                        user_inputs.setdefault(0, {})
                        user_inputs[0][sub_question.name] = sub_question.extract(request).get("user_input")
            else:
                for sub_question in self.sub_questions:
                    name = sub_question.form_name
                    if key.startswith(name + "_"):
                        index = int(key.rsplit("_", 1)[1])
                        user_inputs.setdefault(index, {})
                        user_inputs[index][sub_question.name] = sub_question.extract(request, index).get("user_input")
        sub_results["user_input"] = user_inputs
        return sub_results


class DynamicForm:
    def __init__(self, questions):
        self.untreated_questions = []
        self.questions = []
        if questions:
            self.untreated_questions = loads(questions)
            self.questions: List[PostUsageQuestion] = PostUsageQuestion.load_questions(self.untreated_questions)

    def render(self, group_question_url: str, group_item_id: int, virtual_inputs: bool = False):
        result = ""
        if self.questions:
            result += "<script>if (!$) { $ = django.jQuery; }</script>"
        for question in self.questions:
            result += question.render(virtual_inputs, group_question_url, group_item_id)
        return mark_safe(result)

    def validate(self, group_question_url: str, group_item_id: int):
        # We need to validate the raw json for types
        for question in self.untreated_questions:
            if question["type"] not in question_types.keys():
                raise Exception(f"type has to be one of {', '.join(question_types.keys())}")
            if question["type"] == GROUP_TYPE_FIELD_KEY and "questions" in question:
                for sub_question in question["questions"]:
                    if sub_question["type"] not in question_types.keys():
                        raise Exception(f"type has to be one of {', '.join(question_types.keys())}")
        for question in self.questions:
            question.validate()
        # Test the rendering, but catch reverse exception if this the item doesn't have an id yet
        # (when creating it the first time)
        try:
            self.render(group_question_url, group_item_id)
        except NoReverseMatch:
            if group_item_id:
                raise
            pass
        # Check for duplicate names
        names = []
        for question in self.questions:
            names.append(question.name)
            if isinstance(question, PostUsageGroupQuestion):
                for sub_question in question.sub_questions:
                    names.append(sub_question.name)
        duplicate_names = [k for k, v in Counter(names).items() if v > 1]
        if duplicate_names:
            raise Exception(f"Question names need to be unique. Duplicates were found: {duplicate_names}")
        # Check that consumable exists and is linked to a number question
        for question in self.questions:
            validate_consumable_for_question(question)
            if isinstance(question, PostUsageGroupQuestion):
                for sub_question in question.sub_questions:
                    validate_consumable_for_question(sub_question)

    def extract(self, request) -> str:
        results = {}
        required_unanswered_questions = []
        for question in self.questions:
            results[question.name] = question.extract(request)
            required_unanswered_questions.extend(self._check_for_required_unanswered_questions(results, question))
        run_data = dumps(results, indent="\t") if len(results) else ""
        if required_unanswered_questions:
            raise RequiredUnansweredQuestionsException(run_data, required_unanswered_questions)
        return run_data

    def _check_for_required_unanswered_questions(
        self, results: Dict, question: PostUsageQuestion
    ) -> Optional[List[PostUsageQuestion]]:
        # This method will check for required unanswered questions and if some are found, will fill them with blank and return them
        required_unanswered_questions = []
        user_input = results[question.name].get("user_input")
        user_input = user_input.strip() if user_input else user_input
        if not isinstance(question, PostUsageGroupQuestion) and question.required and not user_input:
            results[question.name]["user_input"] = ""
            required_unanswered_questions.append(question)
        elif isinstance(question, PostUsageGroupQuestion):
            blank_user_input = {0: {}}
            for sub_question in question.sub_questions:
                if sub_question.required and (not user_input or not user_input.get(0, {}).get(sub_question.name)):
                    blank_user_input[0][sub_question.name] = ""
                    required_unanswered_questions.append(sub_question)
            if required_unanswered_questions:
                results[question.name]["user_input"] = blank_user_input
        return required_unanswered_questions

    def filter_questions(self, function: Callable[[PostUsageQuestion], bool]) -> List[PostUsageQuestion]:
        results = []
        for question in self.questions:
            if function(question):
                results.append(question)
            elif isinstance(question, PostUsageGroupQuestion):
                for sub_question in question.sub_questions:
                    if function(sub_question):
                        results.append(sub_question)
        return results

    def charge_for_consumables(self, usage_event, request=None):
        customer = usage_event.user
        merchant = usage_event.operator
        project = usage_event.project
        run_data = usage_event.run_data
        try:
            run_data_json = loads(run_data)
        except Exception as error:
            dynamic_form_logger.debug(error)
            return
        for question in self.questions:
            input_data = run_data_json[question.name] if question.name in run_data_json else None
            withdraw_consumable_for_question(question, input_data, customer, merchant, project, usage_event, request)
            if isinstance(question, PostUsageGroupQuestion):
                for sub_question in question.sub_questions:
                    withdraw_consumable_for_question(
                        sub_question, input_data, customer, merchant, project, usage_event, request
                    )

    def update_tool_counters(self, run_data: str, tool_id: int):
        # This function increments all counters associated with the given tool
        try:
            run_data_json = loads(run_data)
        except Exception as error:
            dynamic_form_logger.debug(error)
            return
        active_counters = ToolUsageCounter.objects.filter(is_active=True, tool_id=tool_id)
        for counter in active_counters:
            additional_value = 0
            for question in self.questions:
                input_data = run_data_json[question.name] if question.name in run_data_json else None
                additional_value += get_counter_increment_for_question(
                    question, input_data, counter.tool_usage_question
                )
                if isinstance(question, PostUsageGroupQuestion):
                    for sub_question in question.sub_questions:
                        additional_value += get_counter_increment_for_question(
                            sub_question, input_data, counter.tool_usage_question
                        )
            if additional_value:
                counter.value += additional_value
                counter.save()


def get_submitted_user_inputs(user_data: str) -> Dict:
    """Takes the user data as a string and returns a dictionary of inputs or a list of inputs for group fields"""
    user_input = {}
    user_data_json = loads(user_data)
    for field_name, data in user_data_json.items():
        if data["type"] != "group":
            user_input[field_name] = data["user_input"]
        else:
            user_input[field_name] = data["user_input"].values()
    return user_input


def render_group_questions(request, questions, group_question_url, group_item_id, group_name) -> str:
    question_index = request.GET["index"]
    virtual_inputs = bool(strtobool((request.GET["virtual_inputs"])))
    if questions:
        for question in PostUsageQuestion.load_questions(loads(questions), question_index):
            if isinstance(question, PostUsageGroupQuestion) and question.group_name == group_name:
                return question.render_group_question(virtual_inputs, group_question_url, group_item_id)
    return ""


def validate_consumable_for_question(question: PostUsageQuestion):
    if question.consumable:
        if not isinstance(question, PostUsageNumberFieldQuestion):
            raise Exception("Consumable withdrawals can only be used in questions of type number")
        else:
            try:
                Consumable.objects.get(name=question.consumable)
            except Consumable.DoesNotExist:
                raise Exception(
                    f"Consumable with name '{question.consumable}' could not be found. Make sure the names match."
                )


def withdraw_consumable_for_question(question, input_data, customer, merchant, project, usage_event, request):
    if isinstance(question, PostUsageNumberFieldQuestion):
        if question.consumable:
            consumable = Consumable.objects.get(name=question.consumable)
            quantity = 0
            if input_data and "user_input" in input_data and input_data["user_input"]:
                if isinstance(input_data["user_input"], dict):
                    for user_input in input_data["user_input"].values():
                        if question.name in user_input and user_input[question.name]:
                            quantity += int(user_input[question.name])
                else:
                    quantity = int(input_data["user_input"])
            if quantity > 0:
                make_withdrawal(
                    consumable_id=consumable.id,
                    customer_id=customer.id,
                    merchant=merchant,
                    quantity=quantity,
                    project_id=project.id,
                    usage_event=usage_event,
                    request=request,
                )


def get_counter_increment_for_question(question, input_data, counter_question):
    additional_value = 0
    if isinstance(question, PostUsageNumberFieldQuestion) or isinstance(question, PostUsageFloatFieldQuestion):
        if question.name == counter_question and "user_input" in input_data and input_data["user_input"]:
            if isinstance(input_data["user_input"], dict):
                for user_input in input_data["user_input"].values():
                    if question.name in user_input and user_input[question.name]:
                        additional_value += float(user_input[question.name])
            else:
                additional_value = float(input_data["user_input"])
    return additional_value


def validate_dynamic_form_model(dynamic_form_json: str, group_url: str, item_id) -> List[str]:
    errors = []
    if dynamic_form_json:
        try:
            loads(dynamic_form_json)
        except ValueError:
            errors.append("This field needs to be a valid JSON string")
        try:
            dynamic_form = DynamicForm(dynamic_form_json)
            dynamic_form.validate(group_url, item_id)
        except KeyError as e:
            errors.append(f"{e} property is required")
        except Exception:
            error_info = sys.exc_info()
            errors.append(error_info[0].__name__ + ": " + str(error_info[1]))
    return errors


def admin_render_dynamic_form_preview(dynamic_form_json: str, group_url: str, item_id):
    form_validity_div = ""
    rendered_form = ""
    try:
        rendered_form = DynamicForm(dynamic_form_json).render(group_url, item_id)
        if dynamic_form_json:
            form_validity_div = '<div id="form_validity"></div>'
    except:
        pass
    return mark_safe(
        '<div class="dynamic_form_preview">{}{}</div><div class="help dynamic_form_preview_help">Save form to preview</div>'.format(
            rendered_form, form_validity_div
        )
    )


question_types: Dict[str, Type[PostUsageQuestion]] = {
    "number": PostUsageNumberFieldQuestion,
    "float": PostUsageFloatFieldQuestion,
    "textbox": PostUsageTextFieldQuestion,
    "textarea": PostUsageTextAreaFieldQuestion,
    "radio": PostUsageRadioQuestion,
    "checkbox": PostUsageCheckboxQuestion,
    "dropdown": PostUsageDropdownQuestion,
    "group": PostUsageGroupQuestion,
}
