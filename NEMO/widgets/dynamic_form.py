from json import dumps, loads

from django.utils import timezone
from django.utils.safestring import mark_safe

from NEMO.models import Consumable, ConsumableWithdraw
from NEMO.utilities import quiet_int


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
					required = 'required' if question['required'] else ''
					is_default_choice = 'checked' if question['default_choice'] == choice else ''
					result += f'<label><input type="radio" name="{question["name"]}" value="{choice}" {required} {is_default_choice}>{choice}</label>'
					result += '</div>'
				result += '</div>'
			elif question['type'] == "textbox":
				result += '<div class="form-group">'
				result += f'<label for="{question["name"]}">{question["title"]}</label>'
				input_group_required = True if 'prefix' in question or 'suffix' in question else False
				if input_group_required:
					result += f'<div class="input-group" style="max-width:{question["max-width"]}px">'
				if 'prefix' in question:
					result += f'<span class="input-group-addon">{question["prefix"]}</span>'
				required = 'required' if question['required'] is True else ''
				result += f'<input type="text" class="form-control" name="{question["name"]}" id="{question["name"]}" placeholder="{question["placeholder"]}" {required} style="max-width:{question["max-width"]}px" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off">'
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

	def charge_for_consumable(self, customer, merchant, project, run_data):
		try:
			run_data = loads(run_data)
		except:
			return
		for question in self.questions:
			if 'consumable' in question:
				try:
					consumable = Consumable.objects.get(name=question['consumable'])
					quantity = 0
					if question['type'] == 'textbox':
						if question['name'] in run_data:
							quantity = quiet_int(run_data[question['name']])
					elif question['type'] == 'radio':
						quantity = 1

					if quantity > 0:
						ConsumableWithdraw.objects.create(customer=customer, merchant=merchant, consumable=consumable, quantity=quantity, project=project, date=timezone.now())
				except:
					pass
