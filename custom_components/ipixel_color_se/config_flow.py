"""Config flow for the iPixel Color SE integration."""

import logging
import re
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from . import protocol
from .connection import IPixelConnection, IPixelError
from .const import (
    CONF_DEVICE_TYPE,
    CONF_HEIGHT,
    CONF_WIDTH,
    DOMAIN,
    LOCAL_NAME_PREFIX,
    SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)

MANUAL_ENTRY = "manual"
_MAC_ADDRESS = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")


class CannotConnectError(Exception):
    """The panel couldn't be reached or didn't answer."""


class UnsupportedPanelError(Exception):
    """The panel answered with a type we don't know."""


def is_ipixel(service_info: BluetoothServiceInfoBleak) -> bool:
    """Return whether an advertisement comes from an iPixel panel.

    Matches the bluetooth matchers in manifest.json.
    """
    return (
        service_info.name.startswith(LOCAL_NAME_PREFIX)
        or SERVICE_UUID in service_info.service_uuids
    )


async def async_read_panel_info(
    hass: HomeAssistant, address: str, name: str
) -> protocol.PanelInfo:
    """Connect to a panel, read its type and resolution, then disconnect.

    The request is set_time with HA's time, so it also sets the panel's clock.
    """
    connection = IPixelConnection(hass, address, name)
    try:
        await connection.async_connect()
        frame = await connection.async_request(protocol.set_time(dt_util.now()))
    except IPixelError as err:
        _LOGGER.debug("Reading the info of %s failed: %s", address, err)
        raise CannotConnectError from err
    finally:
        await connection.async_disconnect()
    try:
        return protocol.parse_panel_info(frame)
    except ValueError as err:
        _LOGGER.debug("Unsupported panel %s: %s", address, err)
        raise UnsupportedPanelError from err


class IPixelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an iPixel display: find it, name it, and read its resolution."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with no display chosen."""
        self._address = ""
        self._ble_name = ""
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a panel found by HA's Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._ble_name = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the display's name, proposing the Bluetooth one."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip() or self._ble_name
            if result := await self._async_create(self._address, name, errors):
                return result
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=(user_input or {}).get(CONF_NAME, self._ble_name),
                    ): str
                }
            ),
            description_placeholders={
                "ble_name": self._ble_name,
                "address": self._address,
            },
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the iPixel panels in range that aren't set up yet."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == MANUAL_ENTRY:
                return await self.async_step_manual()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = address
            self._ble_name = self._discovered[address].name
            return await self.async_step_bluetooth_confirm()

        configured = self._async_current_ids(include_ignore=False)
        self._discovered = {
            service_info.address: service_info
            for service_info in async_discovered_service_info(self.hass)
            if service_info.address not in configured and is_ipixel(service_info)
        }
        if not self._discovered:
            return await self.async_step_manual()

        options = [
            SelectOptionDict(value=address, label=f"{service_info.name} ({address})")
            for address, service_info in sorted(self._discovered.items())
        ]
        options.append(SelectOptionDict(value=MANUAL_ENTRY, label=MANUAL_ENTRY))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                            translation_key="device",
                        )
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address and the name of a display."""
        errors: dict[str, str] = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper().replace("-", ":")
            name = user_input[CONF_NAME].strip() or address
            if not _MAC_ADDRESS.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address, raise_on_progress=False)
                self._abort_if_unique_id_configured()
                if result := await self._async_create(address, name, errors):
                    return result
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {vol.Required(CONF_ADDRESS): str, vol.Required(CONF_NAME): str}
                ),
                user_input,
            ),
            errors=errors,
        )

    async def _async_create(
        self, address: str, name: str, errors: dict[str, str]
    ) -> ConfigFlowResult | None:
        """Read the panel's info and create the entry, or fill errors."""
        try:
            info = await async_read_panel_info(self.hass, address, name)
        except CannotConnectError:
            errors["base"] = "cannot_connect"
        except UnsupportedPanelError:
            errors["base"] = "unsupported_panel"
        except Exception:
            _LOGGER.exception("Unexpected error setting up %s", address)
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_DEVICE_TYPE: info.device_type,
                    CONF_WIDTH: info.width,
                    CONF_HEIGHT: info.height,
                },
            )
        return None
