import importlib
import json
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List, Union

from django.conf import settings

from NEMO.models import Consumable, Tool

rates_logger = getLogger(__name__)

class Rates(ABC):

	rates = None

	@abstractmethod
	def load_rates(self):
		pass

	def get_consumable_rates(self, consumables: List[Consumable]) -> Dict[str, str]:
		if self.rates:
			return {consumable.name : self.get_consumable_rate(consumable) for consumable in consumables}

	@abstractmethod
	def get_consumable_rate(self, consumable: Consumable) -> str:
		pass

	def get_tool_rates(self, tools: List[Tool]) -> Dict[str, str]:
		if self.rates:
			return {tool.name : self.get_tool_rate(tool) for tool in tools}

	@abstractmethod
	def get_tool_rate(self, tool: Tool) -> str:
		pass


class NISTRates(Rates):

	consumable_rate_class = 'inventory_rate'
	tool_rate_class = 'primetime_eq_hourly_rate'
	tool_training_rate_class = 'training_individual_hourly_rate'
	tool_training_group_rate_class = 'training_group_hourly_rate'

	full_cost_rate_class = 'full cost'
	shared_cost_rate_class = 'cost shared'

	def load_rates(self, force_reload=False):
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

	def get_consumable_rate(self, consumable) -> str:
		full_cost_rate = self._get_rate_by_table_id_and_class(consumable, self.consumable_rate_class, self.full_cost_rate_class)
		if full_cost_rate:
			return "Cost <b>${:0,.2f}</b>".format(full_cost_rate)

	def get_tool_rate(self, tool: Tool) -> str:
		full_cost_rate = self._get_rate_by_table_id_and_class(tool, self.tool_rate_class, self.full_cost_rate_class)
		shared_cost_rate = self._get_rate_by_table_id_and_class(tool, self.tool_rate_class, self.shared_cost_rate_class)
		if full_cost_rate or shared_cost_rate:
			result = "Tool rates:"
			if tool.is_parent_tool():
				result += "<br> " + tool.name + ":"
			if full_cost_rate:
				result += " Full Cost <b>${:0,.2f}</b>".format(full_cost_rate)
			if shared_cost_rate:
				result += " Shared Cost <b>${:0,.2f}</b>".format(shared_cost_rate)
			if tool.is_parent_tool():
				for child_tool in tool.tool_children_set.all():
					child_full_cost_rate = self._get_rate_by_table_id_and_class(child_tool, self.tool_rate_class, self.full_cost_rate_class)
					child_shared_cost_rate = self._get_rate_by_table_id_and_class(child_tool, self.tool_rate_class, self.shared_cost_rate_class)
					if child_full_cost_rate or child_shared_cost_rate:
						result += "<br> " + child_tool.name + ":"
						if child_full_cost_rate:
							result += " Full Cost <b>${:0,.2f}</b>".format(child_full_cost_rate)
						if child_shared_cost_rate:
							result += " Shared Cost <b>${:0,.2f}</b>".format(child_shared_cost_rate)
			training_rate = self._get_rate_by_table_id_and_class(tool, self.tool_training_rate_class, self.full_cost_rate_class)
			training_group_rate = self._get_rate_by_table_id_and_class(tool, self.tool_training_group_rate_class, self.full_cost_rate_class)
			if training_rate or training_group_rate:
				result += "<br>Training rates:"
				if training_rate:
					result += " Individual <b>${:0,.2f}</b>".format(training_rate)
				if training_group_rate:
					result += " Group <b>${:0,.2f}</b>".format(training_group_rate)
			return result


	def _get_rate_by_table_id_and_class(self, item: Union[Consumable, Tool], table_id, rate_claz) -> float:
		if self.rates:
			matching_rates = list(filter(lambda rate: rate['table_id'] == table_id and rate['rate_class'] == rate_claz and rate['item_id'] == item.id, self.rates))
			if matching_rates:
				return matching_rates[0]['rate']


def get_rate_class():
	rates_class = getattr(settings, "RATES_CLASS", "NEMO.rates.NISTRates")
	assert isinstance(rates_class, str)
	pkg, attr = rates_class.rsplit(".", 1)
	ret = getattr(importlib.import_module(pkg), attr)
	return ret()


rate_class = get_rate_class()