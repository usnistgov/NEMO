import ast
import operator
from _ast import BinOp, Name, NameConstant, Num, Slice, Subscript, UnaryOp

# supported operators
base_operators = {
	ast.Add: operator.add,
	ast.Sub: operator.sub,
	ast.Mult: operator.mul,
	ast.Div: operator.truediv,
	ast.Pow: operator.pow,
	ast.BitXor: operator.xor,
	ast.USub: operator.neg,
	ast.mod: operator.mod,
}


class BasicEvaluatorVisitor(ast.NodeVisitor):
	def __init__(self, **kwargs):
		self._variables = kwargs

	def visit_Name(self, node: Name):
		return self._variables[node.id]

	def visit_Num(self, node: Num):
		return node.n

	def visit_NameConstant(self, node: NameConstant):
		return node.value

	def visit_UnaryOp(self, node: UnaryOp):
		val = self.visit(node.operand)
		return base_operators[type(node.op)](val)

	def visit_BinOp(self, node: BinOp):
		lhs = self.visit(node.left)
		rhs = self.visit(node.right)
		return base_operators[type(node.op)](lhs, rhs)

	def visit_Subscript(self, node: Subscript):
		val = self.visit(node.value)
		index = self.visit(node.slice)
		try:
			return val[index]
		except AttributeError:
			return self.generic_visit(node)

	def visit_Index(self, node, **kwargs):
		"""df.index[4]"""
		return self.visit(node.value)

	def visit_Slice(self, node: Slice):
		lower = node.lower
		if lower is not None:
			lower = self.visit(lower)
		upper = node.upper
		if upper is not None:
			upper = self.visit(upper)
		step = node.step
		if step is not None:
			step = self.visit(step)

		return slice(lower, upper, step)

	def generic_visit(self, node):
		raise ValueError("malformed node or string: " + repr(node))


def evaluate_expression(expr, **kwargs):
	v = BasicEvaluatorVisitor(**kwargs)
	return v.visit(ast.parse(expr, mode="eval").body)
