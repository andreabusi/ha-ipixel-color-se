"""Controller of one iPixel display: desired state, connection and restore."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
import dataclasses
from datetime import datetime
from functools import partial
import logging
from time import monotonic
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_address_present,
    async_register_advertisement_callback,
    async_track_unavailable,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import protocol
from .connection import IPixelConnection, IPixelError
from .const import CONF_DEVICE_TYPE, CONF_HEIGHT, CONF_WIDTH, DOMAIN
from .protocol import PanelInfo, SendPlan
from .state import DisplayState, Mode

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY = 1.0

# Seconds to wait after a failed connection attempt before reconnecting by
# ourselves again (F3.3). A command still connects at once.
RECONNECT_COOLDOWN = 30.0

# When the time is synced on schedule, in HA's time zone (F6.5). Just after
# midnight the clock also gets the new date (F6.6), although the panel moves
# to the next day by itself (check V3); at 03:05 the European daylight saving
# changes are over.
SYNC_WITH_DATE = {"hour": 0, "minute": 0, "second": 5}
SYNC_AFTER_DST = {"hour": 3, "minute": 5, "second": 0}

type IPixelConfigEntry = ConfigEntry[IPixelController]


def create_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the Store that keeps a display's desired state."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


class IPixelController:
    """Hold what one display should show, and keep the panel showing it.

    The desired state changes only after the panel accepted a command, and
    is saved at once. Every new connection restores it on the panel.

    Entities register a listener and read the controller when it calls them;
    they never read each other.
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
        self.state = DisplayState()
        self.reachable = False
        """Whether HA's Bluetooth sees the panel advertising."""
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
        self._store = create_store(hass, entry.entry_id)
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubscribers: list[CALLBACK_TYPE] = []
        # Held by every operation that talks to the panel: a command, or a
        # connection and its restore, never interleave
        self._lock = asyncio.Lock()
        self._connect_task: asyncio.Task[None] | None = None
        self._retry_after = 0.0
        self._needs_restore = False
        self._lost = False
        self._stopped = False

    @property
    def connected(self) -> bool:
        """Return whether the panel is connected."""
        return self._connection.connected

    @property
    def available(self) -> bool:
        """Return whether a command can reach the panel (T1).

        The panel stops advertising while connected (check V4), so HA's
        Bluetooth eventually forgets it: then the connection alone counts.
        """
        return self.connected or self.reachable

    @property
    def clock_shown(self) -> bool:
        """Return whether the panel should be showing the clock right now."""
        return self.state.mode is Mode.CLOCK and self.state.power

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Call update_callback whenever the state changes. Return a remover."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            self._listeners.remove(update_callback)

        return remove_listener

    async def async_load(self) -> None:
        """Read the saved desired state."""
        if (data := await self._store.async_load()) is not None:
            self.state = DisplayState.from_dict(data)

    @callback
    def async_start(self) -> None:
        """Follow the panel's advertisements, and connect if it's in range.

        Setup never waits for the panel, so HA starts fine while it's off.
        The advertisement callback doesn't replay past advertisements, so the
        first attempt is made here.
        """
        self._unsubscribers = [
            async_register_advertisement_callback(
                self.hass, self._async_advertisement, self.address
            ),
            async_track_unavailable(
                self.hass, self._async_unavailable, self.address, connectable=True
            ),
            async_track_time_change(
                self.hass,
                partial(self._async_scheduled_sync, with_date=True),
                **SYNC_WITH_DATE,
            ),
            async_track_time_change(
                self.hass,
                partial(self._async_scheduled_sync, with_date=False),
                **SYNC_AFTER_DST,
            ),
        ]
        self._async_set_reachable(
            async_address_present(self.hass, self.address, connectable=True)
        )
        if self.reachable:
            self._async_reconnect_soon()
        else:
            _LOGGER.debug(
                "%s isn't in range, waiting for it to advertise", self.address
            )

    async def async_stop(self) -> None:
        """Stop reconnecting, free the panel and save the state."""
        self._stopped = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers = []
        await self._async_cancel_reconnect()
        await self._connection.async_disconnect()
        # Don't leave a delayed save behind: a reload would read stale data
        await self._store.async_save(self._data_to_save())

    async def async_set_power(self, on: bool) -> None:
        """Turn the screen on or off.

        On shows the content again: the clock gets the time, the date and the
        options that changed while the screen was off.
        """
        async with self._async_operation():
            if on:
                await self._async_show_content()
            else:
                await self._connection.async_send(protocol.power(False))
            self._async_update(power=on)

    async def async_set_brightness(self, level: int) -> None:
        """Set the brightness, in percent.

        It turns the screen back on (check V1), so Power follows (F5.4).
        """
        async with self._async_operation():
            await self._connection.async_send(protocol.brightness(level))
            await self._async_refresh_woken_clock()
            self._async_update(brightness=level, power=True)

    async def async_set_orientation(self, value: int) -> None:
        """Set the orientation, whatever is shown (F11.2).

        Like brightness, it turns the screen back on (check V1).
        """
        async with self._async_operation():
            await self._connection.async_send(protocol.orientation(value))
            await self._async_refresh_woken_clock()
            self._async_update(orientation=value, power=True)

    async def async_show_clock(self) -> None:
        """Show the clock with the current options and HA's time (F7.2).

        The clock turns the screen on (F5.3), and set_time follows it.
        """
        async with self._async_operation():
            await self._connection.async_send(self._clock_plan())
            await self._async_send_time()
            self._async_update(mode=Mode.CLOCK, power=True)

    async def async_set_clock(self, **changes: Any) -> None:
        """Change the options of the clock (F6.3, D10).

        They're always saved, but sent only while the clock is shown and the
        panel connected. Otherwise showing the clock, turning the screen on
        or the restore after the next connection applies them. If the panel
        doesn't accept them, the restore runs before the next command.
        """
        self._async_update(clock=dataclasses.replace(self.state.clock, **changes))
        async with self._async_operation(connect=False) as connected:
            if not connected or not self.clock_shown:
                return
            try:
                await self._connection.async_send(self._clock_plan())
            except IPixelError:
                self._needs_restore = True
                raise

    async def async_sync_time(self) -> None:
        """Send HA's time now, connecting if needed (F6.7).

        set_time turns the screen back on (check V7), so Power follows, and
        the clock, if it's the content, is sent again with today's date.
        """
        async with self._async_operation():
            await self._async_sync_time(with_date=True)
            self._async_update(power=True)

    async def async_set_auto_reconnect(self, on: bool) -> None:
        """Choose whether to reconnect by ourselves (F3.2).

        Turned on, it reconnects at once if the panel is in range (F3.5).
        """
        self._async_update(auto_reconnect=on)
        if on:
            self._retry_after = 0.0
            if self.reachable:
                self._async_reconnect_soon()

    async def async_disconnect(self) -> None:
        """Free the panel for the phone app (F3.6).

        Turns off Auto reconnect, or HA would take the panel straight back. A
        command, or turning Auto reconnect on, connects again.
        """
        self._async_update(auto_reconnect=False)
        await self._async_cancel_reconnect()
        async with self._lock:
            await self._connection.async_disconnect()

    @asynccontextmanager
    async def _async_operation(self, *, connect: bool = True) -> AsyncIterator[bool]:
        """Hold the lock, with the panel connected and restored.

        Connect first if needed, unless connect is False: then yield False
        when the panel isn't connected, and True otherwise. Change the state
        inside the block, after the panel accepted the commands. Panel errors
        become translated errors, for the UI and automations (T2).
        """
        async with self._lock:
            if not connect and not self.connected:
                yield False
                return
            try:
                await self._async_connect()
            except IPixelError as err:
                raise self._error("not_reachable") from err
            try:
                if self._needs_restore:
                    await self._async_restore()
                yield True
            except IPixelError as err:
                self.last_error = str(err)
                raise self._error("command_failed", error=str(err)) from err

    async def _async_connect(self) -> None:
        """Connect unless connected. Pause background reconnects if it fails.

        Call with the lock held.
        """
        if self.connected:
            return
        try:
            await self._connection.async_connect()
        except IPixelError as err:
            _LOGGER.debug("Connecting to %s failed: %s", self.address, err)
            self.last_error = str(err)
            self._retry_after = monotonic() + RECONNECT_COOLDOWN
            self._async_notify()
            raise

    async def _async_restore(self) -> None:
        """Bring the panel back to the desired state (plan §4.3).

        Runs on every new connection, also the first one after HA starts: HA
        can't know whether the panel lost power meanwhile, and a power cycle
        boots it with the screen on, showing its built-in GIFs. Call with the
        lock held.
        """
        state = self.state
        send = self._connection.async_send
        _LOGGER.debug("Restoring the state of %s", self.address)
        await self._async_send_time()
        await send(protocol.orientation(state.orientation))
        if state.brightness is not None:
            await send(protocol.brightness(state.brightness))
        # set_time, orientation and brightness turn the screen on (checks V1
        # and V7): off goes last. On shows the content again.
        if state.power:
            await self._async_show_content(sync_time=False)
        else:
            await send(protocol.power(False))
        self._needs_restore = False

    async def _async_show_content(self, *, sync_time: bool = True) -> None:
        """Turn the screen on, showing the content again. Call with the lock held.

        The clock turns the screen on by itself. It gets HA's time first,
        unless sync_time is False: scheduled syncs skip a screen that's off,
        because set_time would turn it on (check V7). With no known content,
        the panel just turns the screen on, showing what it had.
        """
        if self.state.mode is not Mode.CLOCK:
            await self._connection.async_send(protocol.power(True))
            return
        if sync_time:
            await self._async_send_time()
        await self._connection.async_send(self._clock_plan())

    def _clock_plan(self) -> SendPlan:
        """Return the command that shows the clock, with today's date in HA."""
        clock = self.state.clock
        return protocol.clock_mode(
            clock.style, clock.format_24h, clock.show_date, dt_util.now()
        )

    async def _async_send_time(self) -> None:
        """Set the panel's time to HA's (F6.4). Call with the lock held."""
        await self._connection.async_request(protocol.set_time(dt_util.now()))

    async def _async_sync_time(self, *, with_date: bool) -> None:
        """Send HA's time and, if with_date, the clock with today's date.

        set_time turns the screen on (check V7), showing the clock if it's
        the content. Call with the lock held.
        """
        await self._async_send_time()
        if with_date and self.state.mode is Mode.CLOCK:
            await self._connection.async_send(self._clock_plan())

    async def _async_refresh_woken_clock(self) -> None:
        """Show the clock again if a command just turned the screen back on.

        Brightness and orientation turn the screen on (check V1), showing the
        clock the panel had: its time, date or options may be stale. Call
        before recording power, with the lock held.
        """
        if not self.state.power and self.state.mode is Mode.CLOCK:
            await self._async_show_content()

    @callback
    def _async_scheduled_sync(self, _now: datetime, *, with_date: bool) -> None:
        """Sync the time on schedule (F6.5, F6.6), if connected and on.

        It never reconnects: with Auto reconnect off the panel stays free.
        It skips a screen that's off, because set_time would turn it on
        (check V7): turning the screen on syncs the time instead.
        """
        if self.connected and self.state.power:
            self.entry.async_create_background_task(
                self.hass,
                self._async_sync_if_connected(with_date=with_date),
                f"{DOMAIN} sync time {self.address}",
            )

    async def _async_sync_if_connected(self, *, with_date: bool) -> None:
        """Sync the time unless the connection dropped or the screen went off."""
        try:
            async with self._async_operation(connect=False) as connected:
                if connected and self.state.power:
                    _LOGGER.debug("Syncing the time of %s", self.address)
                    await self._async_sync_time(with_date=with_date)
        except HomeAssistantError as err:
            _LOGGER.warning("Syncing the time of %s failed: %s", self.address, err)

    @callback
    def _async_reconnect_soon(self) -> None:
        """Connect and restore in the background, unless it isn't the time."""
        if (
            self.connected
            or not self.state.auto_reconnect
            or self._connect_task is not None
            or self._stopped
            or self.hass.is_stopping
            or monotonic() < self._retry_after
        ):
            return
        self._connect_task = self.entry.async_create_background_task(
            self.hass, self._async_reconnect(), f"{DOMAIN} connect {self.address}"
        )

    async def _async_reconnect(self) -> None:
        """Connect and restore, logging failures instead of raising them."""
        try:
            # This task starts eagerly, inside the advertisement callback,
            # which runs before HA's Bluetooth records the advertisement:
            # yield so the panel can be looked up
            await asyncio.sleep(0)
            async with self._lock:
                try:
                    await self._async_connect()
                except IPixelError:
                    return
                if not self._needs_restore:
                    return
                try:
                    await self._async_restore()
                except IPixelError as err:
                    # Tried again before the next command
                    _LOGGER.warning(
                        "Restoring the state of %s failed: %s", self.address, err
                    )
                    self.last_error = str(err)
        finally:
            self._connect_task = None

    async def _async_cancel_reconnect(self) -> None:
        """Stop a background connection attempt, if one is running."""
        if (task := self._connect_task) is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            self._connect_task = None

    @callback
    def _async_advertisement(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Reconnect when the panel advertises: it does only while disconnected.

        Called for every advertisement, once per scanner that hears it.
        """
        if not service_info.connectable:
            return
        self._async_set_reachable(True)
        self._async_reconnect_soon()

    @callback
    def _async_unavailable(self, _service_info: BluetoothServiceInfoBleak) -> None:
        """Record that HA's Bluetooth no longer sees the panel."""
        self._async_set_reachable(False)

    @callback
    def _async_set_reachable(self, reachable: bool) -> None:
        """Record whether the panel is advertising, telling entities if it changed."""
        if reachable != self.reachable:
            self.reachable = reachable
            self._async_notify()

    @callback
    def _handle_connected(self) -> None:
        """Record a new connection, which needs a restore."""
        self.last_connected = dt_util.utcnow()
        self.last_error = None
        self._needs_restore = True
        if self._lost:
            self._lost = False
            _LOGGER.info("Reconnected to %s", self.address)
        self._async_notify()

    @callback
    def _handle_disconnected(self, expected: bool) -> None:
        """Record a disconnect, warning when it wasn't asked for."""
        self.last_disconnected = dt_util.utcnow()
        # HA's Bluetooth may have forgotten the panel while it was connected
        # and silent (check V4): ask again
        self.reachable = async_address_present(
            self.hass, self.address, connectable=True
        )
        if not expected:
            self._lost = True
            _LOGGER.warning("Lost the connection to %s", self.address)
        self._async_notify()

    @callback
    def _async_update(self, **changes: Any) -> None:
        """Change the desired state, save it and tell the entities."""
        self.state = dataclasses.replace(self.state, **changes)
        self._store.async_delay_save(self._data_to_save, SAVE_DELAY)
        self._async_notify()

    def _data_to_save(self) -> dict[str, Any]:
        """Return the data for the Store, read when it's written."""
        return self.state.as_dict()

    def _error(self, key: str, **placeholders: str) -> HomeAssistantError:
        """Return a translated error about this display."""
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"name": self.entry.title, **placeholders},
        )

    @callback
    def _async_notify(self) -> None:
        """Tell every listener that the state changed."""
        for update_callback in list(self._listeners):
            update_callback()
