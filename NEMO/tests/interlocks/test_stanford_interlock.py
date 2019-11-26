import struct
from socket import socket
from unittest import mock

from django.conf import settings
from django.test import TestCase

# This method will be used by the mock to replace socket.send
# In the stanford interlock case, it will return a list of byte
from NEMO.models import Tool, Interlock, InterlockCard, InterlockCardCategory, User

server1 = 'server1.nist.gov'
server2 = 'https://server2.nist.gov'
port1 = 80
port2 = 8080

def mocked_socket_send(*args, **kwargs):
	class MockSocket(socket):

		def __init__(self):
			super().__init__()
			self.response = None
			self.address = None

		def send(self, data: bytes, flags: int = ...) -> int:
			schema = struct.Struct('!20siiiiiiiiibbbbb18s')
			message_to_be_sent = schema.unpack(data)
			card_number = message_to_be_sent[2]
			even_port = message_to_be_sent[3]
			odd_port = message_to_be_sent[4]
			channel = message_to_be_sent[5]
			command_type = message_to_be_sent[7]
			command_result = 1 # success

			# server2 port 2 channel 2 will send a command failed back
			if self.address[0] == server2 and self.address[1] == port2 and channel == 2:
				command_result = 0 # fail

			# created the response to be sent later
			response_schema = struct.Struct('!iiiiiiiiibbbbb')
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
				0,  # SD overload
				0,  # RD overload
				0,  # ADC done
				0,  # Busy
				0,  # Instruction return value
			)
			pass

		def connect(self, address) -> None:
			self.address = address
			pass

		def recv(self, bufsize: int, flags: int = ...) -> bytes:
			return self.response

	return MockSocket()

class StanfordInterlockTestCase(TestCase):
	tool: Tool = None
	wrong_response_interlock: Interlock = None
	bad_interlock: Interlock = None

	def setUp(self):
		global tool, wrong_response_interlock, bad_interlock
		# enable interlock functionality
		settings.__setattr__('INTERLOCKS_ENABLED', True)
		even_port = 124
		odd_port = 125
		interlock_card_category = InterlockCardCategory.objects.get(name='Stanford')
		interlock_card = InterlockCard.objects.create(server=server1, port=port1, number=1, even_port=even_port, odd_port=odd_port, category=interlock_card_category)
		interlock_card2 = InterlockCard.objects.create(server=server2, port=port2, number=1, even_port=even_port, odd_port=odd_port, category=interlock_card_category)
		interlock = Interlock.objects.create(card=interlock_card, channel=1)
		wrong_response_interlock = Interlock.objects.create(card=interlock_card2, channel=2)
		bad_interlock = Interlock.objects.create(card=interlock_card2, channel=3)
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner, interlock=interlock)

	@mock.patch('NEMO.interlocks.socket.socket', side_effect=mocked_socket_send)
	def test_all_good(self,  mock_args):
		self.assertTrue(tool.interlock.unlock())
		self.assertEquals(tool.interlock.state, Interlock.State.UNLOCKED)
		self.assertTrue(tool.interlock.lock())
		self.assertEquals(tool.interlock.state, Interlock.State.LOCKED)

	@mock.patch('NEMO.interlocks.socket.socket', side_effect=mocked_socket_send)
	def test_server2_command_fail(self, mock_args):
		self.assertFalse(wrong_response_interlock.unlock())
		self.assertEquals(wrong_response_interlock.state, Interlock.State.UNKNOWN)
		self.assertTrue('failed' in wrong_response_interlock.most_recent_reply)
		self.assertTrue('command return value = 0' in wrong_response_interlock.most_recent_reply)
		self.assertFalse(wrong_response_interlock.lock())
		self.assertEquals(wrong_response_interlock.state, Interlock.State.UNKNOWN)
		self.assertTrue('failed' in wrong_response_interlock.most_recent_reply)
		self.assertTrue('command return value = 0' in wrong_response_interlock.most_recent_reply)

