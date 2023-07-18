from typing import Generic, Iterator, TypeVar

from django.db.models import QuerySet

_Z = TypeVar("_Z")


# Special QuerySet type for type hints, very useful when iterating etc.
class QuerySetType(Generic[_Z], QuerySet):
	def __iter__(self) -> Iterator[_Z]:
		...
