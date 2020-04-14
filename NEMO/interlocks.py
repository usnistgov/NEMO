import socket
import struct
from abc import ABC, abstractmethod
from logging import getLogger
from typing import Dict
from xml.etree import ElementTree

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from NEMO.admin import InterlockCardAdminForm, InterlockAdminForm
from NEMO.exceptions import InterlockError
from NEMO.models import Interlock as Interlock_model, InterlockCardCategory
from NEMO.utilities import format_datetime

interlocks_logger = getLogger(__name__)


class Interlock(ABC):
	"""
	This interface allows for customization of Interlock features.
	The only method that has to be implemented is the abstract method "send_command" which send a LOCKED parameter when
	the interlock needs to be locked, and an UNLOCKED parameter when it needs to be unlocked

	The method "clean_interlock_card" can be implemented to set validation rules for the interlock card with the same category

	The interlock type should be set at the end of this file in the dictionary. The key is the key from InterlockCategory, the value is the Interlock implementation.
	"""

	def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
		pass

	def clean_interlock(self, interlock_form: InterlockAdminForm):
		pass

	def lock(self, interlock: Interlock_model) -> {True, False}:
		return self.__issue_command(interlock, Interlock_model.State.LOCKED)

	def unlock(self, interlock: Interlock_model) -> {True, False}:
		return self.__issue_command(interlock, Interlock_model.State.UNLOCKED)

	def __issue_command(self, interlock: Interlock_model, command_type: Interlock_model.State):
		interlocks_enabled = getattr(settings, 'INTERLOCKS_ENABLED', False)
		if not interlocks_enabled or not interlock.card.enabled:
			interlock.most_recent_reply = "Interlock interface mocked out because settings.INTERLOCKS_ENABLED = False or interlock card is disabled. Interlock last set on " + format_datetime(timezone.now()) + "."
			interlock.state = command_type
			interlock.save()
			return True

		state = Interlock_model.State.UNKNOWN
		error_message = ''
		# try to send the command to the interlock
		try:
			state = self._send_command(interlock, command_type)
		except InterlockError as error:
			interlocks_logger.error(error)
			error_message = error.message
		except Exception as error:
			interlocks_logger.error(error)
			error_message = str(error)

		# save interlock state
		interlock.state = state
		interlock.most_recent_reply = Interlock.__create_reply_message(command_type, state, error_message)
		interlock.save()

		# log some useful information
		if interlock.state == interlock.State.UNKNOWN:
			interlocks_logger.error(f"Interlock {interlock.id} is in an unknown state. {interlock.most_recent_reply}")
		elif interlock.state == interlock.State.LOCKED:
			interlocks_logger.debug(f"Interlock {interlock.id} locked successfully at {format_datetime(timezone.now())}")
		elif interlock.state == interlock.State.UNLOCKED:
			interlocks_logger.debug(f"Interlock {interlock.id} unlocked successfully at {format_datetime(timezone.now())}")

		# If the command type equals the current state then the command worked which will return true:
		return interlock.state == command_type

	@staticmethod
	def __create_reply_message(command_type: Interlock_model.State, actual_state: Interlock_model.State, error_message: str) -> str:
		# Compose the status message of the last command.
		reply_message = f"Reply received at {format_datetime(timezone.now())}. "
		if command_type == Interlock_model.State.UNLOCKED:
			reply_message += "Unlock"
		elif command_type == Interlock_model.State.LOCKED:
			reply_message += "Lock"
		else:
			reply_message += "Unknown"
		reply_message += " command "
		if command_type == actual_state and not error_message:
			reply_message += "succeeded."
		else:
			reply_message += "failed. " + error_message
		return reply_message

	@abstractmethod
	def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
		pass


class NoOpInterlock(Interlock):

	def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
		pass

class StanfordInterlock(Interlock):

	def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
		even_port = interlock_card_form.cleaned_data['even_port']
		odd_port = interlock_card_form.cleaned_data['odd_port']
		number = interlock_card_form.cleaned_data['number']
		error = {}
		if not even_port and even_port != 0:
			error['even_port'] = _('This field is required.')
		if not odd_port and odd_port != 0:
			error['odd_port'] = _('This field is required.')
		if not number and number != 0:
			error['number'] = _('This field is required.')
		if error:
			raise ValidationError(error)

	def clean_interlock(self, interlock_form: InterlockAdminForm):
		channel = interlock_form.cleaned_data['channel']
		error = {}
		if not channel:
			error['channel'] = _('This field is required.')
		if error:
			raise ValidationError(error)

	def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
		# The string in this next function call identifies the format of the interlock message.
		# '!' means use network byte order (big endian) for the contents of the message.
		# '20s' means that the message begins with a 20 character string.
		# Each 'i' is an integer field (4 bytes).
		# Each 'b' is a byte field (1 byte).
		# '18s' means that the message ends with a 18 character string.
		# More information on Python structs can be found at:
		# http://docs.python.org/library/struct.html
		command_schema = struct.Struct('!20siiiiiiiiibbbbb18s')
		command_message = command_schema.pack(
			b'EQCNTL_BEGIN_COMMAND',
			1,  # Instruction count
			interlock.card.number,
			interlock.card.even_port,
			interlock.card.odd_port,
			interlock.channel,
			0,  # Command return value
			command_type,  # Type
			0,  # Command
			0,  # Delay
			0,  # SD overload
			0,  # RD overload
			0,  # ADC done
			0,  # Busy
			0,  # Instruction return value
			b'EQCNTL_END_COMMAND'
		)

		# Create a TCP socket to send the interlock command.
		sock = socket.socket()
		try:
			sock.settimeout(3.0)  # Set the send/receive timeout to be 3 seconds.
			server_address = (interlock.card.server, interlock.card.port)
			sock.connect(server_address)
			sock.send(command_message)
			# The reply schema is the same as the command schema except there are no start and end strings.
			reply_schema = struct.Struct('!iiiiiiiiibbbbb')
			reply = sock.recv(reply_schema.size)
			reply = reply_schema.unpack(reply)

			# Update the state of the interlock in the database if the command succeeded.
			if reply[5]:
				interlock_state = command_type
				return interlock_state
			else:
				# raise an exception if it failed
				reply_message = "Stanford Interlock exception:\nResponse information: " +\
								"Instruction count = " + str(reply[0]) + ", " +\
								"card number = " + str(reply[1]) + ", " +\
								"even port = " + str(reply[2]) + ", " +\
								"odd port = " + str(reply[3]) + ", " +\
								"channel = " + str(reply[4]) + ", " +\
								"command return value = " + str(reply[5]) + ", " +\
								"instruction type = " + str(reply[6]) + ", " +\
								"instruction = " + str(reply[7]) + ", " +\
								"delay = " + str(reply[8]) + ", " +\
								"SD overload = " + str(reply[9]) + ", " +\
								"RD overload = " + str(reply[10]) + ", " +\
								"ADC done = " + str(reply[11]) + ", " +\
								"busy = " + str(reply[12]) + ", " +\
								"instruction return value = " + str(reply[13]) + "."
				raise InterlockError(interlock=interlock, msg=reply_message)

		# Log any errors that occurred during the operation into the database.
		except OSError as error:
			reply_message = "Socket error"
			if error.errno:
				reply_message += " " + str(error.errno)
			reply_message += ": " + str(error)
			raise InterlockError(interlock=interlock, msg=reply_message)
		except struct.error as error:
			reply_message = "Response format error: " + str(error)
			raise InterlockError(interlock=interlock, msg=reply_message)
		except InterlockError:
			raise
		except Exception as error:
			reply_message = "General exception: " + str(error)
			raise InterlockError(interlock=interlock, msg=reply_message)
		finally:
			sock.close()


class ProXrInterlock(Interlock):
	"""
	Support for ProXR relay controllers.
	See https://ncd.io/proxr-quick-start-guide/ for more about ProXR.
	"""
	# proxr relay status
	PXR_RELAY_OFF = 0
	PXR_RELAY_ON = 1

	def clean_interlock(self, interlock_form: InterlockAdminForm):
		"""Validates NEMO interlock configuration."""
		channel = interlock_form.cleaned_data['channel']
		error = {}
		if channel not in range(1, 9):
			error['channel'] = _('Relay must be 1-8.')
		if error:
			raise ValidationError(error)

	def _send_bytes(self, relay_socket, proxrcmd):
		"""
		Returns the response from the relay controller.
		Argument relay_socket is a connected socket object.
		Argument proxrcmd (the ProXR command) is an iterable of 8-bit integers.
		"""
		# make sure that all bytes get sent
		bytes_sent = 0
		while bytes_sent < len(proxrcmd):
			bytes_sent += relay_socket.send(bytes(proxrcmd[bytes_sent:]))
		# relay responses can include erroneous data
		# only the last byte of the response is important
		return relay_socket.recv(64)[-1]

	def _get_state(self, relay_socket, interlock_channel):
		"""
		Returns current NEMO state of the relay.
		Argument relay_socket is a connected socket object.
		Argument interlock_channel is the NEMO interlock.channel.
		"""
		state = self._send_bytes(relay_socket, (254, 115 + interlock_channel, 1))
		if state == self.PXR_RELAY_OFF:
			return Interlock_model.State.LOCKED
		elif state == self.PXR_RELAY_ON:
			return Interlock_model.State.UNLOCKED
		else:
			return Interlock_model.State.UNKNOWN

	def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
		"""Returns and sets NEMO locked/unlocked state."""
		state = Interlock_model.State.UNKNOWN
		try:
			with socket.create_connection((interlock.card.server, interlock.card.port), 10) as relay_socket:
				if command_type == Interlock_model.State.LOCKED:
					# turn the interlock channel off
					self._send_bytes(relay_socket, (254, 99 + interlock.channel, 1))
					state = self._get_state(relay_socket, interlock.channel)
				elif command_type == Interlock_model.State.UNLOCKED:
					# turn the interlock channel on
					self._send_bytes(relay_socket, (254, 107 + interlock.channel, 1))
					state = self._get_state(relay_socket, interlock.channel)
		except Exception as error:
			raise InterlockError(interlock=interlock, msg="Communication error: " + str(error))
		return state


class WebRelayHttpInterlock(Interlock):
	WEB_RELAY_OFF = 0
	WEB_RELAY_ON = 1

	def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
		username = interlock_card_form.cleaned_data['username']
		password = interlock_card_form.cleaned_data['password']
		error = {}
		if username and not password:
			error['password'] = _('password is required when using a username.')
		if error:
			raise ValidationError(error)

	def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
		state = Interlock_model.State.UNKNOWN
		try:
			if command_type == Interlock_model.State.LOCKED:
				state = WebRelayHttpInterlock.setRelayState(interlock, WebRelayHttpInterlock.WEB_RELAY_OFF)
			elif command_type == Interlock_model.State.UNLOCKED:
				state = WebRelayHttpInterlock.setRelayState(interlock, WebRelayHttpInterlock.WEB_RELAY_ON)
		except Exception as error:
			raise InterlockError(interlock=interlock, msg="General exception: " + str(error))
		return state

	@staticmethod
	def setRelayState(interlock: Interlock_model, state: {0, 1}) -> Interlock_model.State:
		url = f"{interlock.card.server}:{interlock.card.port}/stateFull.xml?relay{interlock.channel}State={state}"
		if not url.startswith('http') and not url.startswith('https'):
			url = 'http://' + url
		auth = None
		if interlock.card.username and interlock.card.password:
			auth = (interlock.card.username, interlock.card.password)
		response = requests.get(url, auth=auth)
		response.raise_for_status()
		responseXML = ElementTree.fromstring(response.content)
		state = int(responseXML.find(f"relay{interlock.channel}state").text)
		if state == WebRelayHttpInterlock.WEB_RELAY_OFF:
			return Interlock_model.State.LOCKED
		elif state == WebRelayHttpInterlock.WEB_RELAY_ON:
			return Interlock_model.State.UNLOCKED
		else:
			raise Exception(f"Unexpected state received from interlock: {state}")


def get(category: InterlockCardCategory, raise_exception=True):
	"""	Returns the corresponding interlock implementation, and raises an exception if not found. """
	interlock_impl = interlocks.get(category.key, False)
	if not interlock_impl:
		if raise_exception:
			raise Exception(f"There is no interlock implementation for category: {category.name}. Please add one in interlocks.py")
		else:
			return NoOpInterlock()
	else:
		return interlock_impl


interlocks: Dict[str, Interlock] = {
	'stanford': StanfordInterlock(),
	'web_relay_http': WebRelayHttpInterlock(),
	'proxr': ProXrInterlock(),
}
