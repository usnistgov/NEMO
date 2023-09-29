import json
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List, Union

from django.conf import settings

from NEMO.models import Consumable, Tool, User
from NEMO.utilities import get_class_from_settings

rates_logger = getLogger(__name__)


class Rates(ABC):

	rates = None

	@abstractmethod
	def load_rates(self, force_reload=False):
		pass

	def get_consumable_rates(self, consumables: List[Consumable], user: User = None) -> Dict[str, str]:
		if self.rates:
			return {consumable.name : self.get_consumable_rate(consumable, user) for consumable in consumables}

	@abstractmethod
	def get_consumable_rate(self, consumable: Consumable, user: User = None) -> str:
		pass

	def get_tool_rates(self, tools: List[Tool], user: User = None) -> Dict[str, str]:
		if self.rates:
			return {tool.name : self.get_tool_rate(tool, user) for tool in tools}

	@abstractmethod
	def get_tool_rate(self, tool: Tool, user: User = None) -> str:
		pass

	@staticmethod
	def get_expand_rates_table() -> bool:
		from NEMO.views.customization import RatesCustomization
		return RatesCustomization.get_bool("rates_expand_table", raise_exception=False)


class NISTRates(Rates):

	consumable_rate_class = 'inventory_rate'
	tool_rate_class = 'primetime_eq_hourly_rate'
	tool_training_rate_class = 'training_individual_hourly_rate'
	tool_training_group_rate_class = 'training_group_hourly_rate'

	full_cost_rate_class = 'full cost'
	shared_cost_rate_class = 'cost shared'

	def load_rates(self, force_reload=False):
		super().load_rates()
		if force_reload:
			self.rates = None
		if not self.rates:
			json_data = None
			try:
				rates_file = getattr(settings, 'RATES_FILE', settings.MEDIA_ROOT + '/rates.json')
				json_data = open(rates_file)
				self.rates = json.load(json_data)
				rates_logger.info("found rates file and loaded rates")
			except FileNotFoundError as e:
				if hasattr(settings, 'RATES_FILE'):
					rates_logger.exception(e)
				else:
					rates_logger.debug("no rates file, skipping loading rates")
			except Exception as e:
				rates_logger.error("error loading rates")
				rates_logger.exception(e)
			finally:
				if json_data:
					json_data.close()

	def get_consumable_rate(self, consumable: Consumable, user: User = None) -> str:
		full_cost_rate = self._get_rate_by_table_id_and_class(consumable, self.consumable_rate_class, self.full_cost_rate_class)
		if full_cost_rate:
			return "Cost <b>${:0,.2f}</b>".format(full_cost_rate)

	def get_tool_rate(self, tool: Tool, user: User = None) -> str:
		full_cost_rate = self._get_rate_by_table_id_and_class(tool, self.tool_rate_class, self.full_cost_rate_class)
		shared_cost_rate = self._get_rate_by_table_id_and_class(tool, self.tool_rate_class, self.shared_cost_rate_class)
		if not full_cost_rate and not shared_cost_rate:
			return ""
		training_rate = self._get_rate_by_table_id_and_class(tool, self.tool_training_rate_class, self.full_cost_rate_class)
		training_group_rate = self._get_rate_by_table_id_and_class(tool, self.tool_training_group_rate_class, self.full_cost_rate_class)
		html_rate = f'<div class="media"><a onclick="toggle_details(this)" class="pointer collapsed" data-toggle="collapse" data-target="#rates_details"><span class="glyphicon glyphicon-list-alt pull-left notification-icon primary-highlight"></span><span class="glyphicon pull-left chevron glyphicon-chevron-{"down" if self.get_expand_rates_table() else "right"}"></span></a>'
		html_rate += f'<div class="media-body"><span class="media-heading">Rates</span><div id="rates_details" class="collapse {"in" if self.get_expand_rates_table() else ""}"><table class="table table-bordered table-hover thead-light" style="width: auto !important; min-width: 30%; margin-bottom: 0">'

		table_header = '<tr style="font-size: large">'
		table_header_2 = '<tr style="font-size: x-small">'
		table_row = "<tr>"
		if full_cost_rate:
			table_header += '<th class="text-center" style="padding:15px">Standard Rate</th>'
			table_header_2 += '<th class="text-center" style="padding: 1px;">$/Hour</th>'
			table_row += '<td class="text-center" style="vertical-align: middle">${:0,.2f}</td>'.format(full_cost_rate)
		if shared_cost_rate:
			table_header += '<th class="text-center" style="padding:15px">Reduced Rate</th>'
			table_header_2 += '<th class="text-center" style="padding: 1px;">$/Hour</th>'
			table_row += '<td class="text-center" style="vertical-align: middle">${:0,.2f}</td>'.format(shared_cost_rate)
		if training_rate:
			table_header += '<th class="text-center" style="padding:15px">Individual Training</th>'
			table_header_2 += '<th class="text-center" style="padding: 1px;">$/Hour</th>'
			table_row += '<td class="text-center" style="vertical-align: middle">${:0,.2f}</td>'.format(training_rate)
		if training_group_rate:
			table_header += '<th class="text-center" style="padding:15px">Group Training</th>'
			table_header_2 += '<th class="text-center" style="padding: 1px;">$/Hour</th>'
			table_row += '<td class="text-center" style="vertical-align: middle">${:0,.2f}</td>'.format(training_group_rate)
		table_header += "</tr>"
		table_header_2 += "</tr>"
		table_row += "</tr>"
		html_rate += table_header
		html_rate += table_header_2
		html_rate += table_row
		html_rate += "</tr></table></div></div></div>"
		return html_rate

	def _get_rate_by_table_id_and_class(self, item: Union[Consumable, Tool], table_id, rate_claz) -> float:
		if self.rates:
			matching_rates = list(filter(lambda rate: rate['table_id'] == table_id and rate['rate_class'] == rate_claz and rate['item_id'] == item.id, self.rates))
			if matching_rates:
				return matching_rates[0]['rate']


# ONLY import this LOCALLY to avoid potential issues
rate_class: Rates = get_class_from_settings("RATES_CLASS", "NEMO.rates.NISTRates")