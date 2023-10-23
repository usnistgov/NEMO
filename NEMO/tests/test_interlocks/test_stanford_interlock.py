import random
import struct
from socket import socket
from unittest import mock

from django.conf import settings
from django.test import TestCase

from NEMO.interlocks import StanfordInterlock

# This method will be used by the mock to replace socket.send
# In the stanford interlock case, it will return a list of byte
from NEMO.models import Interlock, InterlockCard, InterlockCardCategory, Tool, User

server1 = "server1.nist.gov"
server2 = "https://server2.nist.gov"
port1 = 80
port2 = 8080
channel_command_failed = 10
channel_sd_overload = 11
channel_rd_overload = 12
channel_adc_not_done = 13
channel_busy = 14
channel_out_range = 15


def mocked_socket_send(*args, **kwargs):
    class MockSocket(socket):
        def __init__(self):
            super().__init__()
            self.response = None
            self.address = None

        def send(self, data: bytes, flags: int = ...) -> int:
            schema = struct.Struct("!20sIIIIIIIIIBBBBi18s")
            message_to_be_sent = schema.unpack(data)
            card_number = message_to_be_sent[2]
            even_port = message_to_be_sent[3]
            odd_port = message_to_be_sent[4]
            channel = message_to_be_sent[5]
            command_type = message_to_be_sent[7]
            command_result = 1  # success
            sd_overload = 0
            rd_overload = 0
            adc_done = 1
            busy = 0

            # created the response to be sent later
            response_schema = struct.Struct("!IIIIIIIIIBBBBi")
            return_value = (
                random.randint(StanfordInterlock.MIN_ENABLE_VALUE, StanfordInterlock.MAX_ENABLE_VALUE)
                if command_type == Interlock.State.UNLOCKED
                else random.randint(StanfordInterlock.MIN_DISABLE_VALUE, StanfordInterlock.MAX_DISABLE_VALUE)
            )

            # send errors based on channel
            if self.address[0] == server2 and self.address[1] == port2:
                if channel == channel_command_failed:
                    command_result = 0  # fail
                elif channel == channel_sd_overload:
                    sd_overload = 1
                elif channel == channel_rd_overload:
                    rd_overload = 1
                elif channel == channel_adc_not_done:
                    adc_done = 0
                elif channel == channel_busy:
                    busy = 1
                elif channel == channel_out_range:
                    return_value = 4000 if command_type == Interlock.State.UNLOCKED else 2500

            self.response = response_schema.pack(
                1,  # Instruction count
                card_number,
                even_port,
                odd_port,
                channel,
                command_result,  # Command return value.
                0,  # Instruction type
                0,  # Instruction
                0,  # Delay
                sd_overload,  # SD overload
                rd_overload,  # RD overload
                adc_done,  # ADC done
                busy,  # Busy
                return_value,  # Instruction return value
            )
            pass

        def connect(self, address) -> None:
            self.address = address
            pass

        def recv(self, bufsize: int, flags: int = ...) -> bytes:
            return self.response

    return MockSocket()


class StanfordInterlockTestCase(TestCase):
    def setUp(self):
        # enable interlock functionality
        settings.__setattr__("INTERLOCKS_ENABLED", True)
        even_port = 124
        odd_port = 125
        interlock_card_category = InterlockCardCategory.objects.get(key="stanford")
        interlock_card = InterlockCard.objects.create(
            server=server1,
            port=port1,
            number=1,
            even_port=even_port,
            odd_port=odd_port,
            category=interlock_card_category,
        )
        interlock_card2 = InterlockCard.objects.create(
            server=server2,
            port=port2,
            number=1,
            even_port=even_port,
            odd_port=odd_port,
            category=interlock_card_category,
        )
        self.interlock = Interlock.objects.create(card=interlock_card, channel=1)
        self.command_failed_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_command_failed)
        self.sd_overload_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_sd_overload)
        self.rd_overload_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_rd_overload)
        self.adc_not_done_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_adc_not_done)
        self.relay_busy_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_busy)
        self.out_of_range_interlock = Interlock.objects.create(card=interlock_card2, channel=channel_out_range)
        self.owner = User.objects.create(username="mctest", first_name="Testy", last_name="McTester")
        self.tool = Tool.objects.create(name="test_tool", primary_owner=self.owner, interlock=self.interlock)

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_all_good(self, mock_args):
        self.assertTrue(self.tool.interlock.unlock())
        self.assertEqual(self.tool.interlock.state, Interlock.State.UNLOCKED)
        self.assertTrue(self.tool.interlock.lock())
        self.assertEqual(self.tool.interlock.state, Interlock.State.LOCKED)

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_command_failed(self, mock_args):
        self.assertFalse(self.command_failed_interlock.unlock())
        self.assertEqual(self.command_failed_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.command_failed_interlock.most_recent_reply)
        self.assertTrue("command return value = 0" in self.command_failed_interlock.most_recent_reply)
        self.assertFalse(self.command_failed_interlock.lock())
        self.assertEqual(self.command_failed_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.command_failed_interlock.most_recent_reply)
        self.assertTrue("command return value = 0" in self.command_failed_interlock.most_recent_reply)
        self.assertTrue("Stanford Interlock exception" in self.command_failed_interlock.most_recent_reply)

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_sd_overload(self, mock_args):
        self.assertFalse(self.sd_overload_interlock.unlock())
        self.assertEqual(self.sd_overload_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.sd_overload_interlock.most_recent_reply)
        self.assertTrue("SD overload = 1" in self.sd_overload_interlock.most_recent_reply)
        self.assertTrue("Signal driver overload" in self.sd_overload_interlock.most_recent_reply)
        self.assertFalse(self.sd_overload_interlock.lock())
        self.assertEqual(self.sd_overload_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.sd_overload_interlock.most_recent_reply)
        self.assertTrue("SD overload = 1" in self.sd_overload_interlock.most_recent_reply)
        self.assertTrue("Signal driver overload" in self.sd_overload_interlock.most_recent_reply)

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_rd_overload(self, mock_args):
        self.assertFalse(self.rd_overload_interlock.unlock())
        self.assertEqual(self.rd_overload_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.rd_overload_interlock.most_recent_reply)
        self.assertTrue("RD overload = 1" in self.rd_overload_interlock.most_recent_reply)
        self.assertTrue("Return driver overload" in self.rd_overload_interlock.most_recent_reply)
        self.assertFalse(self.rd_overload_interlock.lock())
        self.assertEqual(self.rd_overload_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.rd_overload_interlock.most_recent_reply)
        self.assertTrue("RD overload = 1" in self.rd_overload_interlock.most_recent_reply)
        self.assertTrue("Return driver overload" in self.rd_overload_interlock.most_recent_reply)
        self.assertFalse(self.rd_overload_interlock.lock())

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_adc_not_done(self, mock_args):
        self.assertFalse(self.adc_not_done_interlock.unlock())
        self.assertEqual(self.adc_not_done_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.adc_not_done_interlock.most_recent_reply)
        self.assertTrue("ADC done = 0" in self.adc_not_done_interlock.most_recent_reply)
        self.assertTrue("ADC not done" in self.adc_not_done_interlock.most_recent_reply)
        self.assertFalse(self.adc_not_done_interlock.lock())
        self.assertEqual(self.adc_not_done_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.adc_not_done_interlock.most_recent_reply)
        self.assertTrue("ADC done = 0" in self.adc_not_done_interlock.most_recent_reply)
        self.assertTrue("ADC not done" in self.adc_not_done_interlock.most_recent_reply)
        self.assertFalse(self.adc_not_done_interlock.lock())

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_relay_busy(self, mock_args):
        self.assertFalse(self.relay_busy_interlock.unlock())
        self.assertEqual(self.relay_busy_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.relay_busy_interlock.most_recent_reply)
        self.assertTrue("busy = 1" in self.relay_busy_interlock.most_recent_reply)
        self.assertTrue("Relay not ready" in self.relay_busy_interlock.most_recent_reply)
        self.assertFalse(self.relay_busy_interlock.lock())
        self.assertEqual(self.relay_busy_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.relay_busy_interlock.most_recent_reply)
        self.assertTrue("busy = 1" in self.relay_busy_interlock.most_recent_reply)
        self.assertTrue("Relay not ready" in self.relay_busy_interlock.most_recent_reply)
        self.assertFalse(self.relay_busy_interlock.lock())

    @mock.patch("NEMO.interlocks.socket.socket", side_effect=mocked_socket_send)
    def test_out_of_range(self, mock_args):
        self.assertFalse(self.out_of_range_interlock.unlock())
        self.assertEqual(self.out_of_range_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.out_of_range_interlock.most_recent_reply)
        self.assertTrue("instruction return value = 4000" in self.out_of_range_interlock.most_recent_reply)
        self.assertTrue("Enable return value exceeds limits" in self.out_of_range_interlock.most_recent_reply)
        self.assertFalse(self.out_of_range_interlock.lock())
        self.assertEqual(self.out_of_range_interlock.state, Interlock.State.UNKNOWN)
        self.assertTrue("failed" in self.out_of_range_interlock.most_recent_reply)
        self.assertTrue("instruction return value = 2500" in self.out_of_range_interlock.most_recent_reply)
        self.assertTrue("Enable return value exceeds limits" in self.out_of_range_interlock.most_recent_reply)
        self.assertFalse(self.out_of_range_interlock.lock())
