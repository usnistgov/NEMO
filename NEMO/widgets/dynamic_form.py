from json import dumps, loads
from logging import getLogger

from django.utils.safestring import mark_safe

from NEMO.models import Consumable
from NEMO.views.consumables import make_withdrawal


dynamic_form_logger = getLogger(__name__)


class DynamicForm:
	def __init__(self, questions):
		self.questions = loads(questions) if questions else None

	def render(self):
		if not self.questions:
			return ''

		result = ''
		for question in self.questions:
			if question['type'] == "radio":
				result += f'<div class="form-group">{question["title"]}'
				for choice in question['choices']:
					result += '<div class="radio">'
					required = 'required' if 'required' in question and question['required'] is True else ''
					is_default_choice = 'checked' if 'default_choice' in question and question['default_choice'] == choice else ''
					result += f'<label><input type="radio" name="{question["name"]}" value="{choice}" {required} {is_default_choice}>{choice}</label>'
					result += '</div>'
				result += '</div>'
			elif question['type'] == "dropdown":
				result += f'<div class="form-group">{question["title"]}'
				required = 'required' if 'required' in question and question['required'] is True else ''
				result += f'<select name="{question["name"]}" id="{question["name"]}" {required} style="margin-top: 5px;max-width:{question["max-width"]}px" class="form-control">'
				blank_disabled = 'disabled="disabled"' if required else ''
				placeholder = question["placeholder"] if 'placeholder' in question else 'Select an option'
				result += f'<option {blank_disabled} selected="selected" value="">{placeholder}</option>'
				for choice in question['choices']:
					is_default_choice = 'selected' if 'default_choice' in question and question['default_choice'] == choice else ''
					result += f'<option value="{choice}" {is_default_choice}>{choice}</option>'
				result += '</select>'
				result += '</div>'
			elif question['type'] == "textbox" or question['type'] == "number":
				result += '<div class="form-group">'
				result += f'<label for="{question["name"]}">{question["title"]}</label>'
				input_group_required = True if 'prefix' in question or 'suffix' in question else False
				if input_group_required:
					result += f'<div class="input-group" style="max-width:{question["max-width"]}px">'
				if 'prefix' in question:
					result += f'<span class="input-group-addon">{question["prefix"]}</span>'
				required = 'required' if 'required' in question and question['required'] is True else ''
				pattern = f'pattern="{question["pattern"]}"' if 'pattern' in question else ''
				placeholder = f'placeholder="{question["placeholder"]}"' if 'placeholder' in question else ''
				if question['type'] == "textbox":
					result += f'<input type="text" class="form-control" name="{question["name"]}" id="{question["name"]}" {placeholder} {pattern} {required} style="max-width:{question["max-width"]}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'
				elif question['type'] == "number":
					minimum = f'min="{question["min"]}"' if 'min' in question else ''
					maximum = f'max="{question["max"]}"' if 'max' in question else ''
					result += f'<input type="number" class="form-control" name="{question["name"]}" id="{question["name"]}" {placeholder} {pattern} {minimum} {maximum} {required} style="max-width:{question["max-width"]}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'
				if 'suffix' in question:
					result += f'<span class="input-group-addon">{question["suffix"]}</span>'
				if input_group_required:
					result += '</div>'
				result += '</div>'

		return mark_safe(result)

	def extract(self, request):
		if not self.questions:
			return ''

		results = {}
		for question in self.questions:
			# Only record the answer when the question was answered. Discard questions that were left blank
			if request.POST.get(question['name']):
				results[question['name']] = request.POST[question['name']]
		return dumps(results, indent='\t', sort_keys=True) if len(results) else ''

	def charge_for_consumables(self, customer, merchant, project, run_data):
		try:
			run_data = loads(run_data)
		except Exception as error:
			dynamic_form_logger.debug(error)
			return
		for question in self.questions:
			if 'consumable' in question:
				try:
					consumable = Consumable.objects.get(name=question['consumable'])
					quantity = 0
					if question['type'] == 'number':
						if question['name'] in run_data:
							quantity = int(run_data[question['name']])

					if quantity > 0:
						make_withdrawal(consumable=consumable, customer=customer, merchant=merchant, quantity=quantity, project=project)
				except Exception as e:
					dynamic_form_logger.warning(f"Could not withdraw consumable: '{question['consumable']}' with quantity: '{run_data[question['name']]}' for customer: '{customer}' by merchant: '{merchant}' for project: '{project}'", e)
					pass
