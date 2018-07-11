from django.forms import Widget
from django.utils.safestring import mark_safe


class PostUsageQuestions(Widget):
	def render(self, name, value, attrs=None, renderer=None):
		result = ""
		for question in value["questions"]:
			result += f'<div>{question.title}</div>'

			if question.type == "radio":
				result += '<div class="radio">'
				for choice in question.choices:
					required = 'required' if question.required else ''
					is_default_choice = 'checked' if question.default_choice == choice else ''
					result += f'<label><input type="radio" name="{question.name}" {required} {is_default_choice}>{choice}</label>'
				result += '</div>'

			elif question.type == "textbox":
				result += '<div class="input-group">'
				if question.prefix:
					result += f'<span class="input-group-addon">{question.prefix}</span>'

				required = 'required' if question.required else ''
				result += f'<input type="text" class="form-control" name="{question.name}" placeholder="{question.placeholder}" {required}>'

				if question.suffix:
					result += f'<span class="input-group-addon">{question.suffix}</span>'
				result += '</div>'

		return mark_safe(result)
