import json
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict, List, Union

from django.conf import settings

from NEMO.models import Consumable, Tool

logger = getLogger(__name__)

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

	def load_rates(self):
		if not self.rates:
			json_data = None
			try:
				json_data = open(settings.RATES_FILE)
				self.rates = json.load(json_data)
				logger.info("found rates file and loaded rates")
			except AttributeError:
				logger.info("no rates file, skipping loading rates")
			except Exception as e:
				logger.error("error loading rates")
				logger.exception(e)
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
			if full_cost_rate:
				result += " Full Cost <b>${:0,.2f}</b>".format(full_cost_rate)
			if shared_cost_rate:
				result += " Shared Cost <b>${:0,.2f}</b>".format(shared_cost_rate)
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
			matching_rates = list(filter(lambda rate: rate['table_id'] == table_id and rate['rate_class'] == rate_claz and rate['item'] == item.name, self.rates))
			if matching_rates:
				return matching_rates[0]['rate']


rate_class = NISTRates()
rate_class.load_rates()