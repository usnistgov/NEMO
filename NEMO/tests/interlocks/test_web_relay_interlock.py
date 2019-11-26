from unittest import mock

from django.conf import settings
from django.test import TestCase

from NEMO.models import User, Tool, InterlockCard, Interlock, InterlockCardCategory

server1 = 'server1.nist.gov'
server2 = 'https://server2.nist.gov'
port1 = 80
port2 = 8080
ERROR_500 = '500 Server Error'
UNLOCK_ERROR = 'unlock: bad interlock'
LOCK_ERROR = 'lock: bad interlock'

bad_interlock: Interlock = None
wrong_response_interlock: Interlock = None
disabled_interlock: Interlock = None

def web_relay_response(relayNumber, state):
	return f"<datavalues>" \
		   f"  <relay{relayNumber}state>{state}</relay{relayNumber}state>" \
		   f"</datavalues>"


# This method will be used by the mock to replace requests.get
# In the web relay case, it will return a xml file with the relay statuses
def mocked_requests_get(*args, **kwargs):
	from requests import Response
	class MockResponse(Response):

		def __init__(self, content, status_code, reason=None):
			super().__init__()
			self.content = content
			self.status_code = status_code
			self.url = args[0]
			self.reason = reason

		def content(self):
			return self.content

	# interlock 3 on server 2 is bad
	if args[0] == f'{bad_interlock.card.server}:{bad_interlock.card.port}/stateFull.xml?relay3State=1':
		return MockResponse('', 500, UNLOCK_ERROR)
	elif args[0] == f'{bad_interlock.card.server}:{bad_interlock.card.port}/stateFull.xml?relay3State=0':
		return MockResponse('', 500, LOCK_ERROR)
	# interlock 2 on server 2 sends wrong response
	elif args[0] == f'{wrong_response_interlock.card.server}:{wrong_response_interlock.card.port}/stateFull.xml?relay2State=0' or args[0] == f'{wrong_response_interlock.card.server}:{wrong_response_interlock.card.port}/stateFull.xml?relay2State=1':
		return MockResponse('bad response', 200)
	elif 'stateFull.xml' in args[0]:
		url_state = args[0][-8:]
		numbers = [int(i) for i in url_state if i.isdigit()]
		relay_number = numbers[0]
		relay_state = numbers[1]
		return MockResponse(web_relay_response(relay_number, relay_state), 200)

	return MockResponse(None, 404)


class WebRelayInterlockTestCase(TestCase):
	tool: Tool = None

	def setUp(self):
		global tool, wrong_response_interlock, bad_interlock, disabled_interlock
		# enable interlock functionality
		settings.__setattr__('INTERLOCKS_ENABLED', True)
		interlock_card_category = InterlockCardCategory.objects.get(name='WebRelayQuadHttp')
		interlock_card = InterlockCard.objects.create(server=server1, port=port1, category=interlock_card_category)
		interlock_card2 = InterlockCard.objects.create(server=server2, port=port2, category=interlock_card_category)
		interlock_card3 = InterlockCard.objects.create(server=server2, port=port2, category=interlock_card_category, enabled=False)
		disabled_interlock = Interlock.objects.create(card=interlock_card3, channel=3)
		interlock = Interlock.objects.create(card=interlock_card, channel=1)
		wrong_response_interlock = Interlock.objects.create(card=interlock_card2, channel=2)
		bad_interlock = Interlock.objects.create(card=interlock_card2, channel=3)
		owner = User.objects.create(username='mctest', first_name='Testy', last_name='McTester')
		tool = Tool.objects.create(name='test_tool', primary_owner=owner, interlock=interlock)

	@mock.patch('NEMO.interlocks.requests.get', side_effect=mocked_requests_get)
	def test_disabled_card(self, mock_args):
		self.assertTrue(disabled_interlock.unlock())
		self.assertEquals(disabled_interlock.state, Interlock.State.UNLOCKED)
		self.assertTrue('Interlock interface mocked out' in disabled_interlock.most_recent_reply)
		self.assertTrue(disabled_interlock.lock())
		self.assertEquals(disabled_interlock.state, Interlock.State.LOCKED)
		self.assertTrue('Interlock interface mocked out' in disabled_interlock.most_recent_reply)

	@mock.patch('NEMO.interlocks.requests.get', side_effect=mocked_requests_get)
	def test_all_good(self, mock_args):
		self.assertTrue(tool.interlock.unlock())
		self.assertEquals(tool.interlock.state, Interlock.State.UNLOCKED)
		self.assertTrue(tool.interlock.lock())
		self.assertEquals(tool.interlock.state, Interlock.State.LOCKED)

	@mock.patch('NEMO.interlocks.requests.get', side_effect=mocked_requests_get)
	def test_error_response_from_interlock(self, mock_args):
		self.assertFalse(bad_interlock.unlock())
		self.assertTrue(ERROR_500 in bad_interlock.most_recent_reply)
		self.assertTrue(UNLOCK_ERROR in bad_interlock.most_recent_reply)
		self.assertEquals(bad_interlock.state, Interlock.State.UNKNOWN)

		self.assertFalse(bad_interlock.lock())
		self.assertTrue(ERROR_500 in bad_interlock.most_recent_reply)
		self.assertTrue(LOCK_ERROR in bad_interlock.most_recent_reply)
		self.assertEquals(bad_interlock.state, Interlock.State.UNKNOWN)

	@mock.patch('NEMO.interlocks.requests.get', side_effect=mocked_requests_get)
	def test_wrong_response_from_interlock(self, mock_args):
		self.assertFalse(wrong_response_interlock.unlock())
		self.assertTrue('General exception' in wrong_response_interlock.most_recent_reply)
		self.assertTrue('syntax error' in wrong_response_interlock.most_recent_reply)
		self.assertEquals(wrong_response_interlock.state, Interlock.State.UNKNOWN)
