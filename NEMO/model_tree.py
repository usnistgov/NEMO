from typing import List, Dict

from django.db.models import QuerySet


class TreeItem:
	""" Helper class for tree items """

	item_type = None
	id: int = None
	item = None
	name: str = None
	tree_category: str = None
	category: str = None
	ancestors: List = []
	descendants: List = []
	children: List = []
	child_items: List = []
	is_leaf: bool = False
	is_root: bool = False

	def ancestor_ids(self, include_self=False):
		ids = [ancestor.id for ancestor in self.ancestors]
		if include_self:
			ids.append(self.id)
		return ids

	def __str__(self):
		return self.name


class ModelTreeHelper:
	"""
	Helper class for trees with models. Create a tree in memory with links to ancestors and descendants
	to help limit database queries.
	"""

	def __init__(self, model_class, parent_field: str = "parent", children_field: str = "children", only_fields=None):
		self.only_fields = ["name", "category"]
		if only_fields is not None:
			self.only_fields.extend(only_fields)
			self.only_fields = list(set(self.only_fields))
		query_set = type(model_class).objects.all().prefetch_related(children_field).only(*self.only_fields)
		self.roots: List = list(query_set.filter(**{f"{parent_field}__isnull": True}))
		self.leaves_queryset: QuerySet = query_set.filter(**{f"{children_field}__isnull": True})
		self.leaf_ids: List[int] = list(
			query_set.filter(**{f"{children_field}__isnull": True}).values_list("id", flat=True)
		)

		self.items: Dict[int, TreeItem] = {}
		self.build_tree(model_class, parent_field, children_field, [], None)
		# Second pass to populate descendants
		for key, item in self.items.items():
			if not item.is_leaf:
				res = []
				for child in item.child_items:
					res.append(self.items[child.id])
				item.children = res.copy()
				result = []
				for key1, item1 in self.items.items():
					if item in item1.ancestors:
						result.append(self.items[item1.id])
				item.descendants = result.copy()

	def build_tree(self, model_class, parent_field, children_field, ancestors: List[TreeItem], items=None):
		is_root = items is None
		if is_root:
			items = self.roots

		for item in items:
			tree_category = "/".join([ancestor.name for ancestor in ancestors])
			if item.category:
				tree_category += "/" + item.category if tree_category else item.category
			tree_item = TreeItem()
			tree_item.id = item.id
			tree_item.name = item.name
			tree_item.item = item
			tree_item.item_type = type(model_class)
			tree_item.tree_category = tree_category
			tree_item.category = item.category
			tree_item.ancestors = ancestors
			tree_item.is_root = is_root
			# Add only fields
			for field in self.only_fields:
				setattr(tree_item, field, getattr(item, field))
			if item.id in self.leaf_ids:
				tree_item.is_leaf = True
			else:
				children = list(
					type(model_class)
						.objects.filter(**{f"{parent_field}__id": item.id})
						.prefetch_related(children_field)
						.only(*self.only_fields)
				)
				tree_item.child_items = children
				tree_item.is_leaf = False
				new_ancestors = ancestors.copy()
				new_ancestors.append(tree_item)
				self.build_tree(model_class, parent_field, children_field, new_ancestors, children)
			self.items[item.id] = tree_item

	def get_areas(self, ids: List[int]) -> List[TreeItem]:
		return [self.items[pk] for pk in ids]

	def get_ancestor_areas(self, tree_items: List[TreeItem], include_self=False):
		return self.get_areas(list(set([pk for tree_item in tree_items for pk in tree_item.ancestor_ids(include_self)])))

	def get_area(self, pk: int) -> TreeItem:
		return self.items.get(pk, None)


def get_area_model_tree():
	from NEMO.models import Area

	only_fields = ["name", "category", "maximum_capacity", "reservation_warning", "count_staff_in_occupancy", "count_service_personnel_in_occupancy"]
	return ModelTreeHelper(Area(), "parent_area", "area_children_set", only_fields)
