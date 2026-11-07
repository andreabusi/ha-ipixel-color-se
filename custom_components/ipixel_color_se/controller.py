"""Controller of one iPixel display: owns its connection and notifies entities."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
import logging

from homeassistant.components.bluetooth import async_address_present
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .connection import IPixelConnection, IPixelError
from .const import CONF_DEVICE_TYPE, CONF_HEIGHT, CONF_WIDTH, DOMAIN
from .protocol import PanelInfo

_LOGGER = logging.getLogger(__name__)

type IPixelConfigEntry = ConfigEntry[IPixelController]


class IPixelController:
    """Keep the connection to one display and tell its entities what changed.

    Entities register a listener and read the controller's state when it
    calls them; they never read each other.
    """

    def __init__(self, hass: HomeAssistant, entry: IPixelConfigEntry) -> None:
        """Set up the controller for a config entry, without connecting."""
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS]
        self.panel = PanelInfo(
            device_type=entry.data[CONF_DEVICE_TYPE],
            width=entry.data[CONF_WIDTH],
            height=entry.data[CONF_HEIGHT],
        )
        self.last_connected: datetime | None = None
        self.last_disconnected: datetime | None = None
        self.last_error: str | None = None
        self._connection = IPixelConnection(
            hass,
            self.address,
            entry.title,
            on_connected=self._handle_connected,
            on_disconnected=self._handle_disconnected,
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self._connect_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        """Return whether the panel is connected."""
        return self._connection.connected

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Call update_callback whenever the state changes. Return a remover."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def async_start(self) -> None:
        """Make the first connection attempt in the background.

        Setup never waits for the panel, so HA starts fine while it's off.
        """
        if not async_address_present(self.hass, self.address, connectable=True):
            _LOGGER.debug("%s isn't in range, not connecting", self.address)
            return
        self._connect_task = self.entry.async_create_background_task(
            self.hass, self._async_connect(), f"{DOMAIN} connect {self.address}"
        )

    async def async_stop(self) -> None:
        """Stop connecting and close the connection, freeing the panel."""
        if self._connect_task is not None:
            self._connect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._connect_task
            self._connect_task = None
        await self._connection.async_disconnect()

    async def _async_connect(self) -> None:
        """Connect, recording the error if it fails."""
        try:
            await self._connection.async_connect()
        except IPixelError as err:
            _LOGGER.debug("Connecting to %s failed: %s", self.address, err)
            self.last_error = str(err)
            self._async_notify()

    @callback
    def _handle_connected(self) -> None:
        """Record a new connection."""
        self.last_connected = dt_util.utcnow()
        self.last_error = None
        self._async_notify()

    @callback
    def _handle_disconnected(self, expected: bool) -> None:
        """Record a disconnect, warning when it wasn't asked for."""
        self.last_disconnected = dt_util.utcnow()
        if not expected:
            _LOGGER.warning("Lost the connection to %s", self.address)
        self._async_notify()

    @callback
    def _async_notify(self) -> None:
        """Tell every listener that the state changed."""
        for update_callback in list(self._listeners):
            update_callback()
