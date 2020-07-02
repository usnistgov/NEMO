from typing import List

from django.forms import Widget
from django.utils.safestring import mark_safe

from NEMO.model_tree import get_area_model_tree, TreeItem
from NEMO.models import User, Tool, ReservationItemType
from NEMO.views.customization import get_customization


class ItemTree(Widget):
	def render(self, name, value, attrs=None, renderer=None):
		"""
		This widget takes a list of items (tools/areas) and creates nested unordered lists in a hierarchical manner.
		The parameters name and attrs are not used.
		'value' is a dictionary which must contain a 'tools' or 'areas' key with a value that is a QuerySet of all tools/areas to be put in the list.
		A collection of unordered HTML lists is returned with various callbacks and properties attached to each nested element.

		For a more concrete example, suppose the following tools are input to the item tree:
		Packaging/Dicing Saw
		Chemical Vapor Deposition/PECVD
		Gen Furnaces/Sinter

		The following unordered HTML list would be produced:
		<ul>
			<li>
				<a href="javascript:void(0);" onclick="on_item_tree_click($(this.nextSibling))" class="node">Packaging</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_item_tree_click($(this))" class="leaf node">Dicing saw</a></li>
				</ul>
			</li>
			<li>
				<a href="javascript:void(0);" onclick="on_item_tree_click($(this.nextSibling))" class="node">Chemical Vapor Deposition</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_item_tree_click($(this))" class="leaf node">PECVD</a></li>
				</ul>
			</li>
			<li>
				<a href="javascript:void(0);" onclick="on_item_tree_click($(this.nextSibling))" class="node">Gen Furnaces</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_item_tree_click($(this))" class="leaf node">Sinter</a></li>
				</ul>
			</li>
		</ul>
		"""
		area_tree = ItemTreeHelper(None, ReservationItemType.AREA)
		tool_tree = ItemTreeHelper(None, ReservationItemType.TOOL)
		user: User = value['user'] if 'user' in value else None
		model_tree = get_area_model_tree()
		area_tree_items: List[TreeItem] = model_tree.get_areas([area.id for area in value.get('areas',[])])
		tools: List[Tool] = value.get('tools',[])
		tool_parent_ids = Tool.objects.filter(parent_tool__isnull=False).values_list('parent_tool_id', flat=True)
		user_accessible_areas = [] if not user or not area_tree_items else user.accessible_areas()
		user_qualified_tool_ids = [] if not user or not tools else user.qualifications.all().values_list('id', flat=True)
		parent_areas_dict = {}
		if area_tree_items:
			# Create a lookup of area name to area with all the parents (in order to display info about category-parents)
			parent_areas_dict = {area_tree_item.name: area_tree_item for area_tree_item in model_tree.get_ancestor_areas(area_tree_items)}
			# Sort areas by complete category
			area_tree_items = list(area_tree_items)
			area_tree_items.sort(key=lambda area: area.tree_category)

		display_all_areas = get_customization('calendar_display_not_qualified_areas') == 'enabled'
		for area in area_tree_items:
			category = area.tree_category + '/' if area.tree_category else ''
			is_qualified = True if not display_all_areas else (user and user.is_staff) or (user and area.item in user_accessible_areas)
			area_tree.add(ReservationItemType.AREA, category + area.name, area.id, is_qualified)
		for tool in tools:
			is_qualified = (user and user.is_staff) or (user and tool.id in user_qualified_tool_ids)
			tool_tree.add(ReservationItemType.TOOL, tool.category + '/' + tool.name_or_child_in_use_name(parent_ids=tool_parent_ids), tool.id,  is_qualified)

		legend = True if area_tree_items and tools else False
		result = ""
		if area_tree_items:
			result += area_tree.render(legend=legend, category_items_lookup=parent_areas_dict)
		if tools:
			result += tool_tree.render(legend=legend)
		return mark_safe(result)


class ItemTreeHelper:
	"""
	This class reads in a textual representation of the organization of each tool/area and renders it to equivalent
	unordered HTML lists.
	"""
	def __init__(self, name, item_type: ReservationItemType):
		self.name = name
		self.item_type = item_type
		self.children = []
		self.id = None
		self.is_user_qualified = False

	def add(self, item_type: ReservationItemType, item, identifier, is_user_qualified):
		"""
		This function takes as input a string representation of the item in the organization hierarchy.
		Example input might be "Imaging and Analysis/Microscopes/Zeiss FIB". The input is parsed with '/' as the
		separator and the tool/area is added to the class' tree structure.
		"""
		part = item.partition('/')
		for child in self.children:
			if child.name == part[0]:
				child.add(item_type, part[2], identifier, is_user_qualified)
				return
		self.children.append(ItemTreeHelper(part[0], item_type))
		if part[2] != '':
			self.children[-1].add(item_type, part[2], identifier, is_user_qualified)
		else:
			self.children[-1].id = identifier
			self.children[-1].is_user_qualified = is_user_qualified
			self.children[-1].item_type = item_type

	def render(self, legend=False, category_items_lookup=None):
		"""
		This function cycles through the root node of the tool/area list and enumerates all the child nodes directly.
		The function assumes that a tree structure of the tools/areas has already been created by calling 'add(...)' multiple
		times. A string of unordered HTML lists is returned.
		"""
		item_type = f"'{self.item_type.value}'"
		result = f'<fieldset class="item_tree_fieldset"><legend align="center" onclick="toggle_item_categories({item_type})">{self.item_type.value.capitalize()}s</legend>' if legend else ''
		result += f'<ul class="nav nav-list item_tree" id="{self.item_type.value}_tree" style="display:none">'
		for child in self.children:
			result += self.__render_helper(child, '', category_items_lookup)
		result += '</fieldset></ul>' if legend else '</ul>'
		return result

	def __render_helper(self, node, result, category_items_lookup=None):
		"""
		Recursively dive through the tree structure and convert it to unordered HTML lists.
		Each node is output as an HTML list item. If the node has children then those are also output.
		"""
		if node.__is_leaf():
			result += '<li>'
			css_class = "" if node.is_user_qualified else 'class="disabled"'
			result += f'<a id="{node.item_type.value}-{node.id}" href="javascript:void(0);" onclick="set_selected_item(this)" data-item-id="{node.id}" data-item-type="{node.item_type.value}" data-item-name="{node.name}" {css_class}>{node.name}</a>'
		if not node.__is_leaf():
			node_li_class = "area-category" if node.item_type == ReservationItemType.AREA else 'tool-category'
			node_list_class = "area-list" if node.item_type == ReservationItemType.AREA else 'tool-list'
			# If we can find this "category" in the list of category_items, then add id, type and name
			extra_data = ''
			if category_items_lookup and node.name in category_items_lookup:
				data = category_items_lookup.get(node.name)
				extra_data = f'id="{node.item_type.value}-{data.id}" data-item-id="{data.id}" data-item-type="{node.item_type.value}" data-item-name="{data.name}"'
			result += f'<li class="{node_li_class}">'
			result += f'<label class="tree-toggler nav-header"><div {extra_data}>{node.name}</div></label><ul class="nav nav-list tree {node_list_class}" data-category="{node.name}">'
			for child in node.children:
				result = self.__render_helper(child, result, category_items_lookup)
			result += '</ul>'
		result += '</li>'
		return result

	def __is_leaf(self):
		""" Test if this node is a leaf (i.e. an actual tool/area). If it is not then the node must be a category. """
		return self.children == []

	def __str__(self):
		""" For debugging, output a string representation of the object in the form: <name [child1, child2, child3, ...]> """
		result = str(self.name)
		if not self.__is_leaf():
			result += ' [' + ', '.join(str(child) for child in self.children) + ']'
		return result
