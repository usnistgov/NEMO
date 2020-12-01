from collections import Counter
from copy import copy
from json import dumps, loads
from logging import getLogger
from typing import Dict, List, Callable

from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from NEMO.models import Consumable, ToolUsageCounter
from NEMO.views.consumables import make_withdrawal

dynamic_form_logger = getLogger(__name__)


class PostUsageQuestion:
	question_type = "Question"

	def __init__(self, properties: Dict, tool_id: int, index: int = None):
		self.properties = properties
		self.tool_id = tool_id
		self.name = self._init_property('name')
		self.title = self._init_property('title')
		self.type = self._init_property('type')
		self.max_width = self._init_property('max-width')
		self.placeholder = self._init_property('placeholder')
		self.prefix = self._init_property('prefix')
		self.suffix = self._init_property('suffix')
		self.pattern = self._init_property('pattern')
		self.min = self._init_property('min')
		self.max = self._init_property('max')
		self.step = self._init_property('step')
		self.consumable = self._init_property('consumable')
		self.required = self._init_property('required', True)
		self.default_choice = self._init_property('default_choice')
		self.choices = self._init_property('choices')
		self.index = index
		if index and not isinstance(self, PostUsageGroupQuestion):
			self.name = f"{self.name}_{index}"
		pass

	def _init_property(self, prop: str, boolean: bool = False):
		if boolean:
			return True if prop in self.properties and self.properties[prop] is True else False
		else:
			return self.properties[prop] if prop in self.properties else None

	def validate(self):
		self.validate_property_exists("name")
		self.validate_property_exists("title")
		self.validate_property_exists("type")

	def render(self) -> str:
		return ''

	def extract(self, request) -> Dict:
		answered_question = copy(self.properties)
		user_input = request.POST.get(self.name)
		if user_input:
			answered_question['user_input'] = user_input
		return answered_question

	def validate_property_exists(self, prop: str):
		try:
			self.properties[prop]
		except KeyError:
			raise Exception(f"{self.question_type} requires property '{prop}' to be defined")

	@staticmethod
	def load_questions(questions: List[Dict], tool_id: int, index: int = None):
		constructor = {
			'number': PostUsageNumberFieldQuestion,
			'textbox': PostUsageTextFieldQuestion,
			'radio': PostUsageRadioQuestion,
			'dropdown': PostUsageDropdownQuestion,
			'group': PostUsageGroupQuestion,
		}
		post_usage_questions: List[PostUsageQuestion] = []
		for question in questions:
			post_usage_questions.append(constructor.get(question['type'], PostUsageQuestion)(question, tool_id, index))
		return post_usage_questions


class PostUsageRadioQuestion(PostUsageQuestion):
	question_type = "Question of type radio"

	def validate(self):
		super().validate()
		self.validate_property_exists("choices")

	def render(self) -> str:
		result = f'<div class="form-group" style="white-space: pre-wrap">{self.title}'
		for choice in self.properties['choices']:
			result += '<div class="radio">'
			required = 'required' if self.required else ''
			is_default_choice = 'checked' if self.default_choice and self.default_choice == choice else ''
			result += f'<label><input type="radio" name="{self.name}" value="{choice}" {required} {is_default_choice}>{choice}</label>'
			result += '</div>'
		result += '</div>'
		return result


class PostUsageDropdownQuestion(PostUsageQuestion):
	question_type = "Question of type dropdown"

	def validate(self):
		super().validate()
		self.validate_property_exists("max-width")
		self.validate_property_exists("choices")

	def render(self) -> str:
		result = f'<div class="form-group" style="white-space: pre-wrap">{self.title}'
		required = 'required' if self.required else ''
		result += f'<select name="{self.name}" {required} style="margin-top: 5px;max-width:{self.max_width}px" class="form-control">'
		blank_disabled = 'disabled="disabled"' if required else ''
		placeholder = self.placeholder if self.placeholder else 'Select an option'
		result += f'<option {blank_disabled} selected="selected" value="">{placeholder}</option>'
		for choice in self.choices:
			is_default_choice = 'selected' if self.default_choice and self.default_choice == choice else ''
			result += f'<option value="{choice}" {is_default_choice}>{choice}</option>'
		result += '</select>'
		result += '</div>'
		return result


class PostUsageTextFieldQuestion(PostUsageQuestion):
	question_type = "Question of type text"

	def validate(self):
		super().validate()
		self.validate_property_exists("max-width")

	def render(self) -> str:
		result = '<div class="form-group">'
		result += f'<label for="{self.name}" style="white-space: pre-wrap">{self.title}</label>'
		input_group_required = True if self.prefix or self.suffix else False
		if input_group_required:
			result += f'<div class="input-group" style="max-width:{self.max_width}px">'
		if self.prefix:
			result += f'<span class="input-group-addon">{self.prefix}</span>'
		required = 'required' if self.required else ''
		pattern = f'pattern="{self.pattern}"' if self.pattern else ''
		placeholder = f'placeholder="{self.placeholder}"' if self.placeholder else ''
		result += self.render_input(required, pattern, placeholder)
		if self.suffix:
			result += f'<span class="input-group-addon">{self.suffix}</span>'
		if input_group_required:
			result += '</div>'
		result += '</div>'
		return result

	def render_input(self, required: str, pattern: str, placeholder: str) -> str:
		return f'<input type="text" class="form-control" name="{self.name}" {placeholder} {pattern} {required} style="max-width:{self.max_width}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'


class PostUsageNumberFieldQuestion(PostUsageTextFieldQuestion):
	question_type = "Question of type number"

	def render_input(self, required: str, pattern: str, placeholder: str) -> str:
		minimum = f'min="{self.min}"' if self.min else ''
		maximum = f'max="{self.max}"' if self.max else ''
		step = f'step="{self.step}"' if self.step else ''
		return f'<input type="number" class="form-control" name="{self.name}" {placeholder} {pattern} {minimum} {maximum} {step} {required} style="max-width:{self.max_width}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'


class PostUsageGroupQuestion(PostUsageQuestion):
	question_type = "Question of type group"

	def __init__(self, properties: Dict, tool_id: int, index: int = None):
		super().__init__(properties, tool_id, index)
		self.max_number = self._init_property('max_number')
		# we need a safe group name to use in js function and variable names
		self.group_name = slugify(self.name).replace("-", "_")
		self.sub_questions: List[PostUsageQuestion] = PostUsageQuestion.load_questions(self._init_property('questions'), tool_id, index)

	def validate(self):
		super().validate()
		self.validate_property_exists('questions')
		self.validate_property_exists('max_number')
		for sub_question in self.sub_questions:
			sub_question.validate()

	def render(self) -> str:
		result = f'<div class="form-group" style="white-space: pre-wrap">{self.title}</div>'
		result += f'<div id="{self.group_name}_container">'
		result += self.render_group_question()
		result += '</div>'
		result += '</div>'
		result += '<div class="form-group">'
		result += f'<button id="{self.group_name}_add_button" type="button" onclick="add_question_{self.group_name}()">Add</button>'
		result += '</div>'
		result += self.render_script()
		return result

	def render_group_question(self) -> str:
		result = ''
		result += f'<div class="{self.group_name}_question" style="padding-top: 10px; padding-bottom: 10px; border-top: 1px solid lightgray">'
		for sub_question in self.sub_questions:
			result += sub_question.render()
		if self.index:
			result += f'<button type="button" onclick="remove_question_{self.group_name}(this);">Remove</button>'
		return result

	def render_script(self):
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
				$.ajax({{ type: "GET", url: "{reverse('tool_usage_group_question', args=[self.tool_id, self.name])}?index="+{self.group_name}_question_index, success : function(response)
				{{
					{self.group_name}_question_index ++;
					$("#{self.group_name}_container").append(response);
					$("body").trigger("question-group-changed");
					update_add_button_{self.group_name}();
				}}
				}});
			}}
		</script>"""

	def extract(self, request) -> Dict:
		# For group question, we also have to look for answers submitted with a numbered suffix (i.e. question, question_1, question_2 etc.)
		# The result of the extraction will be a dictionary, with the keys being the group number, and the values the user inputs for all questions of the group.
		sub_results = copy(self.properties)
		user_inputs = {}
		for key, value in request.POST.items():
			if key in [sub_question.name for sub_question in self.sub_questions]:
				user_inputs.setdefault(0, {})
				user_inputs[0][key] = value
			else:
				for sub_question in self.sub_questions:
					name = sub_question.name
					if key.startswith(name + "_"):
						index = int(key.rsplit("_", 1)[1])
						user_inputs.setdefault(index, {})
						user_inputs[index][name] = value
		sub_results['user_input'] = user_inputs
		return sub_results


class DynamicForm:

	def __init__(self, questions, tool_id):
		self.questions = []
		if questions:
			self.questions: List[PostUsageQuestion] = PostUsageQuestion.load_questions(loads(questions), tool_id)
		self.tool_id = tool_id

	def render(self):
		result = ''
		for question in self.questions:
			result += question.render()
		return mark_safe(result)

	def validate(self):
		for question in self.questions:
			question.validate()
		# Test the rendering
		self.render()
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
			if question.consumable:
				if not isinstance(question, PostUsageNumberFieldQuestion):
					raise Exception("Consumable withdrawals can only be used in questions of type number")
				else:
					try:
						Consumable.objects.get(name=question.consumable)
					except Consumable.DoesNotExist:
						raise Exception(f"Consumable with name '{question.consumable}' could not be found. Make sure the names match.")
			if isinstance(question, PostUsageGroupQuestion):
				for sub_question in question.sub_questions:
					if sub_question.consumable:
						raise Exception("Consumable withdrawals cannot be used in group questions")

	def extract(self, request):
		results = {}
		for question in self.questions:
			results[question.name] = question.extract(request)
		return dumps(results, indent='\t') if len(results) else ''

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

	def charge_for_consumables(self, customer, merchant, project, run_data: str):
		try:
			run_data_json = loads(run_data)
		except Exception as error:
			dynamic_form_logger.debug(error)
			return
		for question in self.questions:
			if question.consumable:
				try:
					consumable = Consumable.objects.get(name=question.consumable)
					quantity = 0
					if isinstance(question, PostUsageNumberFieldQuestion):
						if question.name in run_data_json and 'user_input' in run_data_json[question.name]:
							quantity = int(run_data_json[question.name]['user_input'])
					if quantity > 0:
						make_withdrawal(consumable=consumable, customer=customer, merchant=merchant, quantity=quantity, project=project)
				except Exception as e:
					dynamic_form_logger.warning(f"Could not withdraw consumable: '{question.consumable}' with quantity: '{run_data_json[question.name]}' for customer: '{customer}' by merchant: '{merchant}' for project: '{project}'", e)
					pass

	def update_counters(self, run_data: str):
		# This function increments all counters associated with the tool
		try:
			run_data_json = loads(run_data)
		except Exception as error:
			dynamic_form_logger.debug(error)
			return
		active_counters = ToolUsageCounter.objects.filter(is_active=True, tool_id=self.tool_id)
		for counter in active_counters:
			additional_value = 0
			for question in self.questions:
				if isinstance(question, PostUsageNumberFieldQuestion):
					if question.name == counter.tool_usage_question and question.name in run_data_json and 'user_input' in run_data_json[question.name]:
						additional_value = int(run_data_json[question.name]['user_input'])
				elif isinstance(question, PostUsageGroupQuestion):
					for sub_question in question.sub_questions:
						if sub_question.name == counter.tool_usage_question and question.name in run_data_json and 'user_input' in run_data_json[question.name]:
							for user_input in run_data_json[question.name]['user_input'].values():
								if sub_question.name in user_input:
									additional_value += int(user_input[sub_question.name])
			if additional_value:
				counter.value += additional_value
				counter.save(update_fields=['value'])

