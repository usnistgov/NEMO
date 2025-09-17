from unittest import mock

from django.conf import settings
from django.test import TestCase
from pymodbus import ExceptionResponse
from pymodbus.client import ModbusTcpClient
from pymodbus.pdu import ModbusPDU
from pymodbus.pdu.bit_message import (
    ReadCoilsRequest,
    ReadCoilsResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
)

# This method will be used by the mock to replace socket.send
# In the stanford interlock case, it will return a list of byte
from NEMO.models import Interlock, InterlockCard, InterlockCardCategory, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin

server1 = "server1.nist.gov"
server2 = "https://server2.nist.gov"
port1 = 80
port2 = 8080


def mocked_modbus_client(*args, **kwargs):
    class MockModbusClient(ModbusTcpClient):
        def connect(self):
            return True

        def execute(self, no_response_expected: bool, request: ModbusPDU = None) -> ModbusPDU:
            if isinstance(request, WriteSingleCoilRequest):
                # store value so we can return it later. if server1, good otherwise set to opposite
                if self.comm_params.host == server1:
                    self.tmp_value = request.bits
                else:
                    return ExceptionResponse(request.function_code)
                return WriteSingleCoilResponse()
            elif isinstance(request, ReadCoilsRequest):
                return ReadCoilsResponse(bits=self.tmp_value)
            return ModbusPDU()

    return MockModbusClient(*args, **kwargs)


class ModbusInterlockTestCase(NEMOTestCaseMixin, TestCase):
    tool: Tool = None
    wrong_response_interlock: Interlock = None
    bad_interlock: Interlock = None

    def setUp(self):
        global tool, wrong_response_interlock, bad_interlock
        # enable interlock functionality
        settings.__setattr__("INTERLOCKS_ENABLED", True)
        interlock_card_category = InterlockCardCategory.objects.get(key="modbus_tcp")
        interlock_card = InterlockCard.objects.create(
            server=server1, port=port1, number=1, category=interlock_card_category
        )
        interlock_card2 = InterlockCard.objects.create(
            server=server2, port=port2, number=1, category=interlock_card_category
        )
        interlock = Interlock.objects.create(card=interlock_card, channel=1, unit_id=1)
        wrong_response_interlock = Interlock.objects.create(card=interlock_card2, channel=2)
        bad_interlock = Interlock.objects.create(card=interlock_card2, channel=3)
        owner = User.objects.create(username="mctest", first_name="Testy", last_name="McTester")
        tool = Tool.objects.create(name="test_tool", primary_owner=owner, interlock=interlock)

    @mock.patch("NEMO.interlocks.ModbusTcpClient", side_effect=mocked_modbus_client)
    def test_all_good(self, mock_args):
        self.assertTrue(tool.interlock.unlock())
        self.assertEqual(tool.interlock.state, Interlock.State.UNLOCKED)
        self.assertTrue(tool.interlock.lock())
        self.assertEqual(tool.interlock.state, Interlock.State.LOCKED)

    @mock.patch("NEMO.interlocks.ModbusTcpClient", side_effect=mocked_modbus_client)
    def test_server2_command_fail(self, mock_args):
        self.assertFalse(wrong_response_interlock.unlock())
        self.assertEqual(wrong_response_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("ExceptionResponse" in wrong_response_interlock.most_recent_reply)
        self.assertFalse(wrong_response_interlock.lock())
        self.assertEqual(wrong_response_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("ExceptionResponse" in wrong_response_interlock.most_recent_reply)
