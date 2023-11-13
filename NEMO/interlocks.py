import socket
import struct
from abc import ABC, abstractmethod
from collections import namedtuple
from logging import getLogger
from time import sleep
from typing import Dict, Optional
from xml.etree import ElementTree

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pymodbus.client import ModbusTcpClient

from NEMO.admin import InterlockAdminForm, InterlockCardAdminForm
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

    def lock(self, interlock: Interlock_model) -> bool:
        return self.__issue_command(interlock, Interlock_model.State.LOCKED)

    def unlock(self, interlock: Interlock_model) -> bool:
        return self.__issue_command(interlock, Interlock_model.State.UNLOCKED)

    def __issue_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> bool:
        interlocks_enabled = getattr(settings, "INTERLOCKS_ENABLED", False)
        now = timezone.now()
        if not interlocks_enabled or not interlock.card.enabled:
            interlock.most_recent_reply = (
                "Interlock interface mocked out because settings.INTERLOCKS_ENABLED = False or interlock card is disabled. Interlock last set on "
                + format_datetime(now)
                + "."
            )
            interlock.most_recent_reply_time = now
            interlock.state = command_type
            interlock.save()
            return True

        state = Interlock_model.State.UNKNOWN
        error_message = ""
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
        interlock.most_recent_reply_time = now
        interlock.save()

        # log some useful information
        if interlock.state == interlock.State.UNKNOWN:
            interlocks_logger.error(f"Interlock {interlock.id} is in an unknown state. {interlock.most_recent_reply}")
        elif interlock.state == interlock.State.LOCKED:
            interlocks_logger.debug(f"Interlock {interlock.id} locked successfully at {format_datetime()}")
        elif interlock.state == interlock.State.UNLOCKED:
            interlocks_logger.debug(f"Interlock {interlock.id} unlocked successfully at {format_datetime()}")

        # If the command type equals the current state then the command worked which will return true:
        return interlock.state == command_type

    @staticmethod
    def __create_reply_message(
        command_type: Interlock_model.State, actual_state: Interlock_model.State, error_message: str
    ) -> str:
        # Compose the status message of the last command.
        reply_message = f"Reply received on {format_datetime()}. "
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
    MAX_ENABLE_VALUE = 3800
    MIN_ENABLE_VALUE = 3200
    MAX_DISABLE_VALUE = 1000
    MIN_DISABLE_VALUE = 700

    def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
        even_port = interlock_card_form.cleaned_data["even_port"]
        odd_port = interlock_card_form.cleaned_data["odd_port"]
        number = interlock_card_form.cleaned_data["number"]
        error = {}
        if not even_port and even_port != 0:
            error["even_port"] = _("This field is required.")
        if not odd_port and odd_port != 0:
            error["odd_port"] = _("This field is required.")
        if not number and number != 0:
            error["number"] = _("This field is required.")
        if error:
            raise ValidationError(error)

    def clean_interlock(self, interlock_form: InterlockAdminForm):
        channel = interlock_form.cleaned_data["channel"]
        num_interlocks = interlock_form.cleaned_data["unit_id"]
        error = {}
        if not channel:
            error["channel"] = _("This field is required.")
        if num_interlocks is not None and num_interlocks < 1:
            error["unit_id"] = _("The multiplier must be greater or equal to 1.")
        if error:
            raise ValidationError(error)

    def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
        # The string in this next function call identifies the format of the interlock message.
        # '!' means use network byte order (big endian) for the contents of the message.
        # '20s' means that the message begins with a 20 character string.
        # Each 'I' is an unsigned integer field (4 bytes).
        # Each 'i' is an integer field (4 bytes).
        # Each 'B' is an unsigned char field (1 byte).
        # '18s' means that the message ends with an 18 character string.
        # More information on Python structs can be found at:
        # http://docs.python.org/library/struct.html
        command_schema = struct.Struct("!20sIIIIIIIIIBBBBi18s")
        command_message = command_schema.pack(
            b"EQCNTL_BEGIN_COMMAND",
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
            b"EQCNTL_END_COMMAND",
        )

        # Create a TCP socket to send the interlock command.
        sock = socket.socket()
        try:
            sock.settimeout(3.0)  # Set the send/receive timeout to be 3 seconds.
            server_address = (interlock.card.server, interlock.card.port)
            sock.connect(server_address)
            sock.send(command_message)
            # The reply schema is the same as the command schema except there are no start and end strings.
            reply_schema = struct.Struct("!IIIIIIIIIBBBBi")
            reply = sock.recv(reply_schema.size)
            reply = reply_schema.unpack(reply)

            num_interlocks = interlock.unit_id or 1

            # Check for any interlock errors
            error = ""
            if not reply[5]:
                error = "Stanford Interlock exception"
            elif getattr(settings, "STANFORD_INTERLOCKS_VALIDATE_REPLY", True):
                if reply[9]:
                    error = "Signal driver overload"
                elif reply[10]:
                    error = "Return driver overload"
                elif not reply[11]:
                    error = "ADC not done"
                elif reply[12]:
                    error = "Relay not ready"
                elif not (
                    command_type == Interlock_model.State.UNLOCKED
                    and self.MIN_ENABLE_VALUE * num_interlocks <= reply[13] <= self.MAX_ENABLE_VALUE * num_interlocks
                    or command_type == Interlock_model.State.LOCKED
                    and self.MIN_DISABLE_VALUE * num_interlocks <= reply[13] <= self.MAX_DISABLE_VALUE * num_interlocks
                ):
                    error = "Enable return value exceeds limits"

            if error:
                # raise an exception if it failed
                reply_message = (
                    f"{error}:\nResponse information: "
                    + "Instruction count = "
                    + str(reply[0])
                    + ", "
                    + "card number = "
                    + str(reply[1])
                    + ", "
                    + "even port = "
                    + str(reply[2])
                    + ", "
                    + "odd port = "
                    + str(reply[3])
                    + ", "
                    + "channel = "
                    + str(reply[4])
                    + ", "
                    + "command return value = "
                    + str(reply[5])
                    + ", "
                    + "instruction type = "
                    + str(reply[6])
                    + ", "
                    + "instruction = "
                    + str(reply[7])
                    + ", "
                    + "delay = "
                    + str(reply[8])
                    + ", "
                    + "SD overload = "
                    + str(reply[9])
                    + ", "
                    + "RD overload = "
                    + str(reply[10])
                    + ", "
                    + "ADC done = "
                    + str(reply[11])
                    + ", "
                    + "busy = "
                    + str(reply[12])
                    + ", "
                    + "instruction return value = "
                    + str(reply[13])
                    + "."
                )
                raise InterlockError(interlock=interlock, msg=reply_message)
            # Update the state of the interlock in the database if the command succeeded.
            else:
                interlock_state = command_type
                return interlock_state

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
        channel = interlock_form.cleaned_data["channel"]
        bank = interlock_form.cleaned_data["unit_id"]
        error = {}
        if bank is not None and bank not in range(0, 33):
            error["unit_id"] = _("Bank must be 0-32. Use 0 to trigger all banks.")
        if channel not in range(0, 9):
            error["channel"] = _("Relay must be 0-8. Use 0 to trigger all relays.")
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

    def _get_state(self, relay_socket, interlock_channel, interlock_bank):
        """
        Returns current NEMO state of the relay.
        Argument relay_socket is a connected socket object.
        Argument interlock_channel is the NEMO interlock.channel.
        Argument interlock_bank is the NEMO interlock.unit_id.
        """
        # We cannot read bank 0 since it means all banks, so check the first one
        read_bank = interlock_bank if interlock_bank != 0 else 1
        # We cannot read relay 0 since it means all relays, so check the first one
        read_channel = interlock_channel if interlock_channel != 0 else 1
        state = self._send_bytes(relay_socket, (254, 115 + read_channel, read_bank))
        if state == self.PXR_RELAY_OFF:
            return Interlock_model.State.LOCKED
        elif state == self.PXR_RELAY_ON:
            return Interlock_model.State.UNLOCKED
        else:
            return Interlock_model.State.UNKNOWN

    def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
        """Returns and sets NEMO locked/unlocked state."""
        state = Interlock_model.State.UNKNOWN
        # Backward compatibility, no bank means bank 1
        bank = interlock.unit_id if interlock.unit_id is not None else 1
        try:
            with socket.create_connection((interlock.card.server, interlock.card.port), 10) as relay_socket:
                if command_type == Interlock_model.State.LOCKED:
                    # turn the interlock channel off
                    off_command = (99 + interlock.channel) if interlock.channel != 0 else 129
                    self._send_bytes(relay_socket, (254, off_command, bank))
                    state = self._get_state(relay_socket, interlock.channel, bank)
                elif command_type == Interlock_model.State.UNLOCKED:
                    # turn the interlock channel on
                    on_command = (107 + interlock.channel) if interlock.channel != 0 else 130
                    self._send_bytes(relay_socket, (254, on_command, bank))
                    state = self._get_state(relay_socket, interlock.channel, bank)
        except Exception as error:
            raise InterlockError(interlock=interlock, msg="Communication error: " + str(error))
        return state


class WebRelayHttpInterlock(Interlock):
    WEB_RELAY_OFF = 0
    WEB_RELAY_ON = 1
    state_xml_names = ["stateFull.xml", "state.xml"]
    state_parameter_template = "relay{}"
    state_response_suffixes = ["", "state"]

    def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
        username = interlock_card_form.cleaned_data["username"]
        password = interlock_card_form.cleaned_data["password"]
        error = {}
        if username and not password:
            error["password"] = _("password is required when using a username.")
        if error:
            raise ValidationError(error)

    def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
        state = Interlock_model.State.UNKNOWN
        try:
            if command_type == Interlock_model.State.LOCKED:
                state = self.set_relay_state(interlock, self.WEB_RELAY_OFF)
            elif command_type == Interlock_model.State.UNLOCKED:
                state = self.set_relay_state(interlock, self.WEB_RELAY_ON)
        except Exception as error:
            raise InterlockError(interlock=interlock, msg="General exception: " + str(error))
        return state

    @classmethod
    def set_relay_state(cls, interlock: Interlock_model, state: {0, 1}) -> Interlock_model.State:
        response, auth, response_error = None, None, None
        if interlock.card.username and interlock.card.password:
            auth = (interlock.card.username, interlock.card.password)
        for state_xml_name in cls.state_xml_names:
            url = f"{interlock.card.server}:{interlock.card.port}/{state_xml_name}?{cls.state_parameter_template.format(interlock.channel or '')}={state}"
            if not url.startswith("http") and not url.startswith("https"):
                url = "http://" + url
            response = requests.get(url, auth=auth)
            response_error = cls.check_response_error(response)
            if not response_error:
                break
        # At this point we have tried all combination so raise an error
        if response_error:
            raise Exception(f"Communication error: {response_error}")
        # No errors, continue and read relay state
        response_xml = ElementTree.fromstring(response.content)
        state = None
        # Try with a few different lookups here since depending on the relay model, it could be relayX or relayXstate
        for state_suffix in cls.state_response_suffixes:
            element = response_xml.find(cls.state_parameter_template.format(interlock.channel or "") + state_suffix)
            # Explicitly check for None since 0 is a valid state to return
            if element is not None:
                state = int(element.text)
                break
        if state == cls.WEB_RELAY_OFF:
            return Interlock_model.State.LOCKED
        elif state == cls.WEB_RELAY_ON:
            return Interlock_model.State.UNLOCKED
        else:
            raise Exception(f"Unexpected state received from interlock: {state}")

    @staticmethod
    def check_response_error(response) -> Optional[str]:
        try:
            # If we get a bad status code, there is obviously an error
            response.raise_for_status()
            # Otherwise, check in the content in case the error is in there
            if "404 Error" in response.text:
                raise Exception("File not found")
            elif "401 Error" in response.text:
                raise Exception("Authentication failed")
        except Exception as e:
            return str(e)


class ModbusTcpInterlock(Interlock):
    MODBUS_OFF = 0
    MODBUS_ON = 1

    def clean_interlock(self, interlock_form: InterlockAdminForm):
        channel = interlock_form.cleaned_data["channel"]
        error = {}
        if channel is None:
            error["channel"] = _("This field is required.")
        if error:
            raise ValidationError(error)

    def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
        state = Interlock_model.State.UNKNOWN
        try:
            if command_type == Interlock_model.State.LOCKED:
                state = self.set_relay_state(interlock, self.MODBUS_OFF)
            elif command_type == Interlock_model.State.UNLOCKED:
                state = self.set_relay_state(interlock, self.MODBUS_ON)
        except Exception as error:
            interlocks_logger.exception(error)
            raise Exception("General exception: " + str(error))
        return state

    @classmethod
    def set_relay_state(cls, interlock: Interlock_model, state: {0, 1}) -> Interlock_model.State:
        coil = interlock.channel
        client = ModbusTcpClient(interlock.card.server, port=interlock.card.port)
        try:
            valid_connection = client.connect()
            if not valid_connection:
                raise Exception(
                    f"Connection to server {interlock.card.server}:{interlock.card.port} could not be established"
                )
            kwargs = {"slave": interlock.unit_id} if interlock.unit_id is not None else {}
            write_reply = client.write_coil(coil, state, **kwargs)
            if write_reply.isError():
                raise Exception(str(write_reply))
            sleep(0.3)
            read_reply = client.read_coils(coil, 1, **kwargs)
            if read_reply.isError():
                raise Exception(str(read_reply))
            state = read_reply.bits[0]
            if state == cls.MODBUS_OFF:
                return Interlock_model.State.LOCKED
            elif state == cls.MODBUS_ON:
                return Interlock_model.State.UNLOCKED
        finally:
            client.close()


class WebApiInterlock(Interlock):
    """Set Channel/Relay/Coil in the interlock to specify which tool to turn on/off."""
    ToolState = namedtuple("ToolState", ["name", "endpoint", "interlock_state"])
    OFF = ToolState("off", getattr(settings, "WEB_API_OFF_ENDPOINT"), Interlock_model.State.LOCKED)  # Start with /
    ON = ToolState("on", getattr(settings, "WEB_API_ON_ENDPOINT"), Interlock_model.State.UNLOCKED)  # Start with /

    API_METHOD = getattr(settings, "WEB_API_METHOD", "put")  # Either "put" (default) or "post"
    API_USERNAME = getattr(settings, "WEB_API_USERNAME", None)  # Optional, can be obtained from interlock.card.username
    API_PASSWORD = getattr(settings, "WEB_API_PASSWORD", None)  # Optional, can be obtained from interlock.card.password

    def clean_interlock_card(self, interlock_card_form: InterlockCardAdminForm):
        username = interlock_card_form.cleaned_data["username"]
        password = interlock_card_form.cleaned_data["password"]
        error = {}
        if username and not password:
            error["password"] = _("password is required when using a username.")
        if error:
            raise ValidationError(error)

    def clean_interlock(self, interlock_form: InterlockAdminForm):
        channel = interlock_form.cleaned_data["channel"]
        error = {}
        if not channel:
            error["channel"] = _("This field is required.")
        if error:
            raise ValidationError(error)

    def _send_command(self, interlock: Interlock_model, command_type: Interlock_model.State) -> Interlock_model.State:
        state = Interlock_model.State.UNKNOWN
        try:
            if command_type == self.OFF.interlock_state:
                state = self.set_tool_state(interlock, self.OFF)
            elif command_type == self.ON.interlock_state:
                state = self.set_tool_state(interlock, self.ON)
        except Exception as error:
            raise InterlockError(interlock=interlock, msg="General exception: " + str(error))
        return state

    @classmethod
    def set_tool_state(cls, interlock: Interlock_model, tool_state: ToolState) -> Interlock_model.State:
        status = cls._call_api(interlock, tool_state.endpoint)

        if status == cls.OFF.name:
            return cls.OFF.interlock_state
        elif status == cls.ON.name:
            return cls.ON.interlock_state
        else:
            raise Exception(f"Unexpected status received from API: {status}")

    @classmethod
    def _call_api(cls, interlock: Interlock_model, endpoint: str) -> str:
        """Calls API with the specified endpoint to turn the tool off or on. Returns the status 'off' or 'on'."""
        username = cls.API_USERNAME if cls.API_USERNAME is not None else interlock.card.username
        password = cls.API_PASSWORD if cls.API_PASSWORD is not None else interlock.card.password

        headers = {"username": username, "password": password}
        url = f"{interlock.card.server}:{interlock.card.port}{endpoint}/{interlock.channel}"

        if cls.API_METHOD == "post":
            response = requests.post(url, headers=headers)
        else:
            response = requests.put(url, headers=headers)

        response_error = cls.check_response_error(response)
        if response_error:
            raise Exception(f"Communication error: {response_error}")

        response_data = response.json()
        return response_data["status"]

    @staticmethod
    def check_response_error(response) -> Optional[str]:
        try:
            response.raise_for_status()
            if "404 Error" in response.text:
                raise Exception("File not found")
            elif "401 Error" in response.text:
                raise Exception("Authentication failed")
        except Exception as e:
            return str(e)


def get(category: InterlockCardCategory, raise_exception=True):
    """Returns the corresponding interlock implementation, and raises an exception if not found."""
    interlock_impl = interlocks.get(category.key, False)
    if not interlock_impl:
        if raise_exception:
            raise Exception(
                f"There is no interlock implementation for category: {category.name}. Please add one in interlocks.py"
            )
        else:
            return NoOpInterlock()
    else:
        return interlock_impl


interlocks: Dict[str, Interlock] = {
    "stanford": StanfordInterlock(),
    "web_relay_http": WebRelayHttpInterlock(),
    "modbus_tcp": ModbusTcpInterlock(),
    "proxr": ProXrInterlock(),
    "web_api": WebApiInterlock(),
}
