import csv

from rest_framework.exceptions import ParseError
from rest_framework.parsers import BaseParser


class CSVParser(BaseParser):
	"""
	Parses CSV data.
	The first line must contain field names.
	"""

	media_type = "text/csv"

	def parse(self, stream, media_type=None, parser_context=None):
		parser_context = parser_context or {}
		delimiter = parser_context.get("delimiter", ",")

		try:
			# Decode stream into csv string
			str_data = stream.read().decode("utf-8-sig")
			# Read the csv into a list of rows
			rows = csv.reader(str_data.splitlines(), dialect=csv.excel, delimiter=delimiter)
			# First row (headers) are field names
			header_row = next(rows)
			# Clean them up
			headers = [c.strip() for c in header_row] if (header_row is not None) else None
			# Create data dict structure
			data = [dict(zip(headers, row)) for row in rows]
			# If only one record return it as json object, otherwise return our list of json object
			return data[0] if len(data) == 1 else data
		except Exception as exc:
			raise ParseError("CSV parse error - %s" % str(exc))
