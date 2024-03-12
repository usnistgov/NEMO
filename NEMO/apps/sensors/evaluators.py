import ast
from typing import List

from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

from NEMO.apps.sensors.models import Sensor
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

# Special functions that are executed on the modbus client itself and require a complete connection
modbus_client_functions = ["read_coils"]


def get_modbus_function(name):
    # This will return the corresponding modbus function
    def modbus_function(registers):
        decoder = BinaryPayloadDecoder.fromRegisters(registers, byteorder=Endian.Big, wordorder=Endian.Little)
        return getattr(decoder, name)

    return modbus_function


def evaluate_modbus_client_function(sensor: Sensor, name: str, args: List):
    # This will evaluate and return the value of the client function
    client = ModbusTcpClient(sensor.card.server, port=sensor.card.port)
    try:
        valid_connection = client.connect()
        if not valid_connection:
            raise Exception(f"Connection to server {sensor.card.server}:{sensor.card.port} could not be established")
        read_reply = getattr(client, name)(*args)
        if read_reply.isError():
            raise Exception(str(read_reply))
        if name == "read_coils":
            return read_reply.bits[0]
        return read_reply
    finally:
        client.close()


# Extension of the basic evaluator with additional modbus specific functions
# noinspection PyTypeChecker
class ModbusEvaluatorVisitor(BasicEvaluatorVisitor):
    def __init__(self, sensor, **kwargs):
        self.sensor = sensor
        super().__init__(**kwargs)

    def visit_Call(self, node: ast.Call):
        if node.func.id in self.functions:
            return super().visit_Call(node)
        elif node.func.id in modbus_functions:
            function_args = [self.visit(arg) for arg in node.args]
            return get_modbus_function(node.func.id)(*function_args)()
        elif node.func.id in modbus_client_functions:
            function_args = [self.visit(arg) for arg in node.args]
            return evaluate_modbus_client_function(self.sensor, node.func.id, function_args)
        else:
            self.generic_visit(node)


def evaluate_modbus_expression(sensor, **kwargs):
    v = ModbusEvaluatorVisitor(sensor, **kwargs)
    return v.visit(ast.parse(sensor.formula, mode="eval").body)
