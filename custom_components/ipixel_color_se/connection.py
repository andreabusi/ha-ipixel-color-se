"""Bluetooth connection to an iPixel display, through Home Assistant's stack.

Going through HA's Bluetooth integration (rather than pypixelcolor's own
transport, which opens a BleakClient by itself) is what makes ESPHome proxies
work.
"""

import asyncio
from collections.abc import Callable
import logging

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.core import HomeAssistant, callback

from .const import NOTIFY_UUID, WRITE_UUID
from .protocol import ACK_DONE_STATUS, ACK_WINDOW_STATUSES, SendPlan, ack_status

_LOGGER = logging.getLogger(__name__)

# How long to wait for each ACK and for a response, as pypixelcolor does.
# The panel answers simple commands in about 30 ms.
ACK_TIMEOUT = 8.0
RESPONSE_TIMEOUT = 8.0


class IPixelError(Exception):
    """Base class for errors talking to a panel."""


class IPixelConnectionError(IPixelError):
    """The panel can't be reached, or the connection was lost."""


class IPixelCommandError(IPixelError):
    """A write failed, or the panel didn't answer it."""


class IPixelConnection:
    """One BLE connection to a panel.

    The panel accepts a single connection. Commands are sent one at a time, in
    the order they arrive. Notifications are enabled once per connection, and
    one handler routes every frame to the command in progress.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        *,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[bool], None] | None = None,
    ) -> None:
        """Set up the connection, without connecting.

        on_disconnected gets True when the disconnect was asked for, False
        when the connection dropped.
        """
        self._hass = hass
        self._address = address
        self._name = name
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._client: BleakClientWithServiceCache | None = None
        self._connect_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        # Frames for the command in progress; None means the connection is gone
        self._frames: asyncio.Queue[bytes | None] | None = None

    @property
    def connected(self) -> bool:
        """Return whether the connection is up."""
        return self._client is not None and self._client.is_connected

    async def async_connect(self) -> None:
        """Connect, unless already connected.

        Serialized, so a background reconnect and a command can't open two
        connections.
        """
        async with self._connect_lock:
            if self.connected:
                return
            device = async_ble_device_from_address(
                self._hass, self._address, connectable=True
            )
            if device is None:
                raise IPixelConnectionError(
                    f"{self._address} isn't in range of a connectable adapter or proxy"
                )

            def latest_device() -> BLEDevice:
                """Return the freshest BLEDevice for retries: the proxy may change."""
                return (
                    async_ble_device_from_address(
                        self._hass, self._address, connectable=True
                    )
                    or device
                )

            _LOGGER.debug("Connecting to %s", self._address)
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    self._name,
                    disconnected_callback=self._handle_disconnect,
                    ble_device_callback=latest_device,
                )
            except (BleakError, TimeoutError) as err:
                raise IPixelConnectionError(
                    f"Can't connect to {self._address}: {err}"
                ) from err
            try:
                await client.start_notify(NOTIFY_UUID, self._handle_notification)
            except (BleakError, TimeoutError) as err:
                await self._async_close(client)
                raise IPixelConnectionError(
                    f"Can't enable notifications on {self._address}: {err}"
                ) from err
            self._client = client
            _LOGGER.debug("Connected to %s", self._address)
            if self._on_connected:
                self._on_connected()

    async def async_disconnect(self) -> None:
        """Close the connection on purpose."""
        async with self._connect_lock:
            client, self._client = self._client, None
            if client is None:
                return
            self._wake_sender()
            await self._async_close(client)
            _LOGGER.debug("Disconnected from %s", self._address)
            if self._on_disconnected:
                self._on_disconnected(True)

    async def async_send(self, plan: SendPlan) -> None:
        """Send a plan, waiting for every ACK it asks for."""
        await self._async_run(plan)

    async def async_request(self, plan: SendPlan) -> bytes:
        """Send a plan and return the panel's response frame."""
        if not plan.response:
            raise ValueError(f"{plan.name} doesn't expect a response")
        if (response := await self._async_run(plan)) is None:
            raise IPixelCommandError(f"No response to {plan.name}")
        return response

    async def _async_run(self, plan: SendPlan) -> bytes | None:
        """Write a plan's windows, wait for its ACKs and maybe a response."""
        async with self._send_lock:
            client = self._client
            if client is None or not client.is_connected:
                raise IPixelConnectionError(f"Not connected to {self._address}")
            # Created before the first write: the panel can answer before the
            # write itself is confirmed
            self._frames = frames = asyncio.Queue()
            try:
                _LOGGER.debug("Sending %s to %s", plan.name, self._address)
                status: int | None = None
                for window in plan.windows:
                    self._discard_stale(frames)
                    await self._async_write(client, window.data, plan.chunk_size)
                    if window.ack:
                        status = await self._async_wait_ack(frames, plan.name)
                if plan.final_ack and status != ACK_DONE_STATUS:
                    await self._async_wait_ack(frames, plan.name, done=True)
                if plan.response:
                    return await self._async_wait_response(frames, plan.name)
                return None
            finally:
                self._frames = None

    async def _async_write(
        self, client: BleakClientWithServiceCache, data: bytes, chunk_size: int
    ) -> None:
        """Write one window in chunks."""
        try:
            for start in range(0, len(data), chunk_size):
                await client.write_gatt_char(
                    WRITE_UUID, data[start : start + chunk_size], response=True
                )
        except (BleakError, TimeoutError) as err:
            raise IPixelCommandError(
                f"Writing to {self._address} failed: {err}"
            ) from err

    async def _async_wait_ack(
        self, frames: asyncio.Queue[bytes | None], name: str, *, done: bool = False
    ) -> int:
        """Wait for a window ACK, or for the end-of-transfer ACK if done."""
        wanted = {ACK_DONE_STATUS} if done else {*ACK_WINDOW_STATUSES, ACK_DONE_STATUS}
        try:
            async with asyncio.timeout(ACK_TIMEOUT):
                while True:
                    frame = await self._async_next_frame(frames)
                    if (status := ack_status(frame)) in wanted:
                        return status
                    _LOGGER.debug("Ignored %s while waiting for an ACK", frame.hex(" "))
        except TimeoutError as err:
            raise IPixelCommandError(
                f"{self._address} didn't acknowledge {name} within {ACK_TIMEOUT} s"
            ) from err

    async def _async_wait_response(
        self, frames: asyncio.Queue[bytes | None], name: str
    ) -> bytes:
        """Wait for the first frame that isn't an ACK."""
        try:
            async with asyncio.timeout(RESPONSE_TIMEOUT):
                while True:
                    frame = await self._async_next_frame(frames)
                    if ack_status(frame) is None:
                        return frame
                    _LOGGER.debug(
                        "Ignored %s while waiting for a response", frame.hex(" ")
                    )
        except TimeoutError as err:
            raise IPixelCommandError(
                f"{self._address} didn't answer {name} within {RESPONSE_TIMEOUT} s"
            ) from err

    async def _async_next_frame(self, frames: asyncio.Queue[bytes | None]) -> bytes:
        """Return the next frame, or raise if the connection is gone."""
        if (frame := await frames.get()) is None:
            raise IPixelConnectionError(f"Lost the connection to {self._address}")
        return frame

    def _discard_stale(self, frames: asyncio.Queue[bytes | None]) -> None:
        """Drop frames left over from the previous window."""
        while not frames.empty():
            if (frame := frames.get_nowait()) is None:
                raise IPixelConnectionError(f"Lost the connection to {self._address}")
            _LOGGER.debug("Discarded stale frame %s", frame.hex(" "))

    def _wake_sender(self) -> None:
        """Tell the command in progress, if any, that the connection is gone."""
        if self._frames is not None:
            self._frames.put_nowait(None)

    async def _async_close(self, client: BleakClientWithServiceCache) -> None:
        """Disconnect a client, ignoring errors: it's going away anyway."""
        try:
            await client.disconnect()
        except BleakError as err:
            _LOGGER.debug("Error disconnecting from %s: %s", self._address, err)

    @callback
    def _handle_notification(self, _sender: object, data: bytearray) -> None:
        """Route a frame from the panel to the command in progress."""
        frame = bytes(data)
        _LOGGER.debug("Received %s from %s", frame.hex(" "), self._address)
        if self._frames is not None:
            self._frames.put_nowait(frame)

    @callback
    def _handle_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle the connection dropping.

        Ignored for clients we already let go, which includes our own
        async_disconnect.
        """
        if client is not self._client:
            return
        self._client = None
        self._wake_sender()
        _LOGGER.debug("Connection to %s dropped", self._address)
        if self._on_disconnected:
            self._on_disconnected(False)
