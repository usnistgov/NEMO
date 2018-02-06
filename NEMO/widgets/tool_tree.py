from django.forms import Widget
from django.utils.safestring import mark_safe


class ToolTree(Widget):
	def render(self, name, value, attrs=None, renderer=None):
		"""
		This widget takes a list of tools and creates nested unordered lists in a hierarchical manner.
		The parameters name and attrs are not used.
		'value' is a dictionary which must contain a 'tools' key with a value that is a QuerySet of all tools to be put in the list.
		A collection of unordered HTML lists is returned with various callbacks and properties attached to each nested element.

		For a more concrete example, suppose the following tools are input to the tool tree:
		Packaging/Dicing Saw
		Chemical Vapor Deposition/PECVD
		Gen Furnaces/Sinter

		The following unordered HTML list would be produced:
		<ul>
			<li>
				<a href="javascript:void(0);" onclick="on_tool_tree_click($(this.nextSibling))" class="node">Packaging</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_tool_tree_click($(this))" class="leaf node">Dicing saw</a></li>
				</ul>
			</li>
			<li>
				<a href="javascript:void(0);" onclick="on_tool_tree_click($(this.nextSibling))" class="node">Chemical Vapor Deposition</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_tool_tree_click($(this))" class="leaf node">PECVD</a></li>
				</ul>
			</li>
			<li>
				<a href="javascript:void(0);" onclick="on_tool_tree_click($(this.nextSibling))" class="node">Gen Furnaces</a>
				<ul class="collapsed">
					<li><a href="javascript:void(0);" onclick="on_tool_tree_click($(this))" class="leaf node">Sinter</a></li>
				</ul>
			</li>
		</ul>
		"""
		tree = ToolTreeHelper(None)
		for tool in value['tools']:
			tree.add(tool.category + '/' + tool.name, tool.id)
		return mark_safe(tree.render())


class ToolTreeHelper:
	"""
	This class reads in a textual representation of the organization of each NanoFab tool and renders it to equivalent
	unordered HTML lists.
	"""
	def __init__(self, name):
		self.name = name
		self.children = []
		self.id = None

	def add(self, tool, identifier):
		"""
		This function takes as input a string representation of the tool in the organization hierarchy.
		Example input might be "Imaging and Analysis/Microscopes/Zeiss FIB". The input is parsed with '/' as the
		separator and the tool is added to the class' tree structure.
		"""
		part = tool.partition('/')
		for child in self.children:
			if child.name == part[0]:
				child.add(part[2], identifier)
				return
		self.children.append(ToolTreeHelper(part[0]))
		if part[2] != '':
			self.children[-1].add(part[2], identifier)
		else:
			self.children[-1].id = identifier

	def render(self):
		"""
		This function cycles through the root node of the tool list and enumerates all the child nodes directly.
		The function assumes that a tree structure of the tools has already been created by calling 'add(...)' multiple
		times. A string of unordered HTML lists is returned.
		"""
		result = '<ul class="nav nav-list" id="tool_tree" style="display:none">'
		for child in self.children:
			result += self.__render_helper(child, '')
		result += '</ul>'
		return result

	def __render_helper(self, node, result):
		"""
		Recursively dive through the tree structure and convert it to unordered HTML lists.
		Each node is output as an HTML list item. If the node has children then those are also output.
		"""
		result += '<li>'
		if node.__is_leaf():
			result += f'<a href="javascript:void(0);" onclick="set_selected_item(this)" data-tool-id="{node.id}" data-type="tool link">{node.name}</a>'
		if not node.__is_leaf():
			result += f'<label class="tree-toggler nav-header"><div>{node.name}</div></label><ul class="nav nav-list tree" data-category="{node.name}">'
			for child in node.children:
				result = self.__render_helper(child, result)
			result += '</ul>'
		result += '</li>'
		return result

	def __is_leaf(self):
		""" Test if this node is a leaf (i.e. an actual tool). If it is not then the node must be a tool category. """
		return self.children == []

	def __str__(self):
		""" For debugging, output a string representation of the object in the form: <name [child1, child2, child3, ...]> """
		result = str(self.name)
		if not self.__is_leaf():
			result += ' [' + ', '.join(str(child) for child in self.children) + ']'
		return result
