import ast

from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

from NEMO.evaluators import BasicEvaluatorVisitor

# Special modbus functions
modbus_functions = [
    "decode_8bit_uint",
    "decode_16bit_uint",
    "decode_32bit_uint",
    "decode_64bit_uint",
    "decode_8bit_int",
    "decode_16bit_int",
    "decode_32bit_int",
    "decode_64bit_int",
    "decode_16bit_float",
    "decode_32bit_float",
    "decode_64bit_float",
    "decode_bits",
    "decode_string",
]


def get_modbus_function(name):
    # This will return the corresponding modbus function
    def modbus_function(registers):
        decoder = BinaryPayloadDecoder.fromRegisters(registers, byteorder=Endian.Big, wordorder=Endian.Little)
        return getattr(decoder, name)

    return modbus_function


# noinspection PyTypeChecker
class ModbusEvaluatorVisitor(BasicEvaluatorVisitor):
    # Extension of the basic evaluator with additional modbus specific functions
    def visit_Call(self, node: ast.Call):
        if node.func.id in self.functions:
            return super().visit_Call(node)
        elif node.func.id in modbus_functions:
            new_args = [self.visit(arg) for arg in node.args]
            return get_modbus_function(node.func.id)(*new_args)()
        else:
            self.generic_visit(node)


def evaluate_modbus_expression(expr, **kwargs):
    v = ModbusEvaluatorVisitor(**kwargs)
    return v.visit(ast.parse(expr, mode="eval").body)
