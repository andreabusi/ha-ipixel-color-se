"""Tests for the controller: state rules, reconnection, restore and errors."""

import asyncio
import dataclasses
from datetime import timedelta

from bleak.exc import BleakError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.ipixel_color_se import connection as connection_module
from custom_components.ipixel_color_se.const import DOMAIN
from custom_components.ipixel_color_se.controller import (
    RECONNECT_COOLDOWN,
    IPixelController,
)
from custom_components.ipixel_color_se.state import ClockSettings, DisplayState, Mode

from .common import FakePanel, ack, describe, panel_date, panel_time
from .test_init import setup_entry

CONNECTED = "binary_sensor.kitchen_pixel_connected"
POWER = "switch.kitchen_pixel_power"
AUTO_RECONNECT = "switch.kitchen_pixel_auto_reconnect"
ORIENTATION = "select.kitchen_pixel_orientation"
MODE = "select.kitchen_pixel_mode"
CLOCK_STYLE = "select.kitchen_pixel_clock_style"

# What a new connection sends when nothing was ever set
DEFAULT_RESTORE = ["set_time", "orientation 0", "power on"]
# The clock with the default options
CLOCK = "clock 1 24h date"


def store_key(entry: MockConfigEntry) -> str:
    """Return the Store key of an entry."""
    return f"{DOMAIN}.{entry.entry_id}"


def save_state(hass_storage: dict, entry: MockConfigEntry, state: DisplayState) -> None:
    """Save a desired state as if HA had run before."""
    hass_storage[store_key(entry)] = {
        "version": 1,
        "minor_version": 1,
        "key": store_key(entry),
        "data": state.as_dict(),
    }


async def start(hass: HomeAssistant, entry: MockConfigEntry) -> IPixelController:
    """Set up a display and return its controller."""
    await setup_entry(hass, entry)
    return entry.runtime_data


async def settle(hass: HomeAssistant) -> None:
    """Wait for background connection attempts too."""
    await hass.async_block_till_done(wait_background_tasks=True)


async def fire_at(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str
) -> None:
    """Move the clock to when and run what was scheduled until then."""
    freezer.move_to(when)
    async_fire_time_changed(hass, dt_util.utcnow())
    await settle(hass)


def ignore(name: str, panel: FakePanel) -> object:
    """Return a responder that doesn't answer the commands named name."""
    return lambda data: [] if describe(data).startswith(name) else panel.answer(data)


@pytest.fixture
def no_ack_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail fast when the panel doesn't acknowledge."""
    monkeypatch.setattr(connection_module, "ACK_TIMEOUT", 0.01)
    monkeypatch.setattr(connection_module, "RESPONSE_TIMEOUT", 0.01)


# Restore (F9, plan §4.3)


async def test_first_connection_restores_only_what_was_set(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A brightness never set isn't sent: the panel keeps its own."""
    await start(hass, mock_config_entry)

    assert mock_panel.commands == DEFAULT_RESTORE


async def test_restore_order(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Time, orientation, brightness, then the screen off."""
    save_state(
        hass_storage,
        mock_config_entry,
        DisplayState(power=False, brightness=40, orientation=2),
    )

    await start(hass, mock_config_entry)

    assert mock_panel.commands == [
        "set_time",
        "orientation 2",
        "brightness 40",
        "power off",
    ]
    assert not mock_panel.screen_on


@pytest.mark.freeze_time("2026-11-07 18:17:02+00:00")
async def test_restore_sends_ha_local_time(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The panel gets HA's time zone, not the system's, which is UTC here (F6.4)."""
    await hass.config.async_set_time_zone("Europe/Rome")

    await start(hass, mock_config_entry)

    # 19:17:02, an hour ahead of UTC in November
    assert mock_panel.writes[0] == bytes.fromhex("08 00 01 80 13 11 02 00")


@pytest.mark.parametrize(
    ("power", "content"), [(True, "clock 4 12h"), (False, "power off")]
)
async def test_restore_shows_the_clock(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    power: bool,
    content: str,
) -> None:
    """The clock comes back with its options, and turns the screen on; off stays off."""
    save_state(
        hass_storage,
        mock_config_entry,
        DisplayState(
            power=power,
            mode=Mode.CLOCK,
            clock=ClockSettings(style=4, format_24h=False, show_date=False),
        ),
    )

    await start(hass, mock_config_entry)

    assert mock_panel.commands == ["set_time", "orientation 0", content]
    assert mock_panel.screen_on is power


@pytest.mark.freeze_time("2026-11-07 23:30:00+00:00")
async def test_clock_shows_ha_local_date(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Past midnight in Rome it's still the 7th in UTC: the clock shows the 8th (F6.4)."""
    await hass.config.async_set_time_zone("Europe/Rome")
    save_state(hass_storage, mock_config_entry, DisplayState(mode=Mode.CLOCK))

    await start(hass, mock_config_entry)

    assert mock_panel.commands == ["set_time", "orientation 0", CLOCK]
    assert panel_time(mock_panel.writes[0]) == "00:30:00"
    assert panel_date(mock_panel.writes[-1]) == "08/11/26 7"


async def test_power_cycle_turns_the_screen_off_again(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After a power cycle the panel reconnects by itself and is restored (F9)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_set_power(False)

    mock_panel.lose_power()
    await hass.async_block_till_done()
    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert "Lost the connection to" in caplog.text

    mock_panel.writes.clear()
    mock_panel.power_on()
    assert mock_panel.screen_on  # it boots with the screen on
    await settle(hass)

    assert hass.states.get(CONNECTED).state == STATE_ON
    assert mock_panel.commands == ["set_time", "orientation 0", "power off"]
    assert not mock_panel.screen_on
    assert hass.states.get(POWER).state == STATE_OFF
    assert "Reconnected to" in caplog.text


async def test_power_cycle_brings_the_clock_back(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """After a power cycle the clock is back, not the built-in GIFs (F9.4)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_show_clock()
    await controller.async_set_clock(style=5)

    mock_panel.lose_power()
    await hass.async_block_till_done()
    mock_panel.writes.clear()
    mock_panel.power_on()
    await settle(hass)

    assert mock_panel.commands == ["set_time", "orientation 0", "clock 5 24h date"]


@pytest.mark.usefixtures("no_ack_wait")
async def test_failed_restore_is_retried_before_the_next_command(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A command never reaches a panel that wasn't restored."""
    mock_panel.responder = ignore("orientation", mock_panel)
    controller = await start(hass, mock_config_entry)

    assert controller.connected
    assert "Restoring the state of AA:BB:CC:DD:EE:FF failed" in caplog.text

    mock_panel.responder = mock_panel.answer
    mock_panel.writes.clear()
    await controller.async_set_brightness(40)

    assert mock_panel.commands == [*DEFAULT_RESTORE, "brightness 40"]

    # Restored now: the next command goes alone
    mock_panel.writes.clear()
    await controller.async_set_brightness(50)
    assert mock_panel.commands == ["brightness 50"]


async def test_commands_wait_for_the_restore(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A command arriving during the restore is sent after it, not in between."""
    loop = asyncio.get_running_loop()

    def slow_orientation(data: bytes) -> list[bytes]:
        if describe(data).startswith("orientation"):
            loop.call_later(0.05, mock_panel.client.notify, ack(data))
            return []
        return mock_panel.answer(data)

    mock_panel.responder = slow_orientation
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await asyncio.sleep(0.01)
    assert mock_panel.commands == ["set_time", "orientation 0"]

    await mock_config_entry.runtime_data.async_set_brightness(40)

    assert mock_panel.commands == [*DEFAULT_RESTORE, "brightness 40"]


# Simple commands and the power rules (plan §5, F5.3)


async def test_commands_update_the_state(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The state follows what the panel accepted."""
    controller = await start(hass, mock_config_entry)
    mock_panel.writes.clear()

    await controller.async_set_brightness(40)
    await controller.async_set_orientation(2)
    await controller.async_set_power(False)

    assert mock_panel.commands == ["brightness 40", "orientation 2", "power off"]
    assert controller.state == DisplayState(power=False, brightness=40, orientation=2)


@pytest.mark.parametrize(
    "command",
    [
        lambda controller: controller.async_set_brightness(40),
        lambda controller: controller.async_set_orientation(2),
        lambda controller: controller.async_sync_time(),
    ],
)
async def test_commands_that_turn_the_screen_on(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    command: object,
) -> None:
    """Brightness, orientation and set_time turn the screen on (V1, V7): Power follows (F5.4)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_set_power(False)
    assert hass.states.get(POWER).state == STATE_OFF

    await command(controller)

    assert mock_panel.screen_on
    assert controller.state.power
    assert hass.states.get(POWER).state == STATE_ON


async def test_changes_are_saved_after_a_second(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One Store per display, written a second after a change."""
    controller = await start(hass, mock_config_entry)

    await controller.async_set_power(False)
    assert store_key(mock_config_entry) not in hass_storage

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()

    assert hass_storage[store_key(mock_config_entry)]["data"] == {
        **DisplayState().as_dict(),
        "power": False,
    }


async def test_state_survives_a_restart(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """After a restart HA starts from the saved state, and restores it (F5.3, T3)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_set_brightness(40)
    await controller.async_set_power(False)
    await controller.async_set_auto_reconnect(False)

    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await settle(hass)

    controller = mock_config_entry.runtime_data
    assert controller.state == DisplayState(
        power=False, brightness=40, auto_reconnect=False
    )
    # Auto reconnect is off: no connection, so nothing sent
    assert not controller.connected
    assert hass.states.get(POWER).state == STATE_OFF


@pytest.mark.parametrize(
    ("setup_panel", "key"),
    [
        # The panel lost power, but HA's Bluetooth still remembers it
        (FakePanel.lose_power, "not_reachable"),
        # The panel doesn't acknowledge
        (lambda panel: setattr(panel, "responder", lambda _data: []), "command_failed"),
    ],
)
@pytest.mark.usefixtures("no_ack_wait")
async def test_failed_command_keeps_the_state(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    setup_panel: object,
    key: str,
) -> None:
    """A command the panel didn't accept raises a translated error (T2)."""
    controller = await start(hass, mock_config_entry)
    setup_panel(mock_panel)

    with pytest.raises(HomeAssistantError) as err:
        await controller.async_set_power(False)

    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == key
    assert err.value.translation_placeholders["name"] == "Kitchen Pixel"
    assert controller.state.power
    assert controller.last_error


# Clock (F6, F7, D10)


async def test_show_clock(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Mode Clock sends the clock and then HA's time, turning the screen on (F5.3)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_set_power(False)
    assert hass.states.get(MODE).state == STATE_UNKNOWN
    mock_panel.writes.clear()

    await controller.async_show_clock()

    assert mock_panel.commands == [CLOCK, "set_time"]
    assert mock_panel.screen_on
    assert controller.state == DisplayState(mode=Mode.CLOCK)
    assert hass.states.get(MODE).state == "clock"
    assert hass.states.get(POWER).state == STATE_ON


@pytest.mark.parametrize(
    ("changes", "command"),
    [
        ({"style": 3}, "clock 3 24h date"),
        ({"format_24h": False}, "clock 1 12h date"),
        ({"show_date": False}, "clock 1 24h"),
    ],
)
async def test_clock_options_update_the_clock_shown(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    changes: dict,
    command: str,
) -> None:
    """While the clock is shown, a change to its options is sent at once (F6.3)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_show_clock()
    mock_panel.writes.clear()

    await controller.async_set_clock(**changes)

    assert mock_panel.commands == [command]
    assert controller.state.clock == dataclasses.replace(ClockSettings(), **changes)


@pytest.mark.parametrize(
    "state",
    [
        DisplayState(),
        DisplayState(power=False),
        DisplayState(mode=Mode.CLOCK, power=False),
    ],
    ids=["unknown mode", "unknown mode, screen off", "clock, screen off"],
)
async def test_clock_options_wait_while_the_clock_is_hidden(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    state: DisplayState,
) -> None:
    """Hidden, the clock isn't sent: it would replace the content or turn the screen on (D10)."""
    save_state(hass_storage, mock_config_entry, state)
    controller = await start(hass, mock_config_entry)
    screen_on = mock_panel.screen_on
    mock_panel.writes.clear()

    await controller.async_set_clock(style=3)

    assert mock_panel.commands == []
    assert mock_panel.screen_on is screen_on
    assert controller.state.clock.style == 3
    assert hass.states.get(CLOCK_STYLE).state == "planet_blue"


async def test_clock_options_show_when_the_screen_turns_on(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Power on shows the clock again, with the time and what changed while off."""
    save_state(
        hass_storage, mock_config_entry, DisplayState(mode=Mode.CLOCK, power=False)
    )
    controller = await start(hass, mock_config_entry)
    await controller.async_set_clock(style=3)
    mock_panel.writes.clear()

    await controller.async_set_power(True)

    assert mock_panel.commands == ["set_time", "clock 3 24h date"]
    assert mock_panel.screen_on
    assert hass.states.get(POWER).state == STATE_ON


@pytest.mark.parametrize(
    ("command", "sent"),
    [
        (lambda controller: controller.async_set_brightness(40), "brightness 40"),
        (lambda controller: controller.async_set_orientation(2), "orientation 2"),
    ],
)
async def test_waking_the_screen_refreshes_the_clock(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    command: object,
    sent: str,
) -> None:
    """Brightness and orientation turn the screen on (check V1): the clock follows."""
    save_state(
        hass_storage, mock_config_entry, DisplayState(mode=Mode.CLOCK, power=False)
    )
    controller = await start(hass, mock_config_entry)
    await controller.async_set_clock(style=3)
    mock_panel.writes.clear()

    await command(controller)
    assert mock_panel.commands == [sent, "set_time", "clock 3 24h date"]
    assert controller.state.power

    # The clock was shown already: the next one goes alone
    mock_panel.writes.clear()
    await command(controller)
    assert mock_panel.commands == [sent]


async def test_clock_options_wait_for_the_connection(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Disconnected, the options are saved without connecting; the restore sends them."""
    controller = await start(hass, mock_config_entry)
    await controller.async_show_clock()
    mock_panel.lose_power()
    await hass.async_block_till_done()
    attempts = mock_panel.connect_attempts

    await controller.async_set_clock(style=3)

    assert mock_panel.connect_attempts == attempts
    assert controller.state.clock.style == 3

    mock_panel.writes.clear()
    mock_panel.power_on()
    await settle(hass)
    assert mock_panel.commands == ["set_time", "orientation 0", "clock 3 24h date"]


async def test_clock_options_dont_take_the_panel_back(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """After Disconnect, a clock option doesn't reconnect: it isn't a command (F3.6)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_show_clock()
    await controller.async_disconnect()
    mock_panel.advertise()

    await controller.async_set_clock(style=3)

    assert not mock_panel.connected
    assert controller.state.clock.style == 3


@pytest.mark.usefixtures("no_ack_wait")
async def test_refused_clock_options_are_restored(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Options the panel didn't accept are kept, and restored before the next command."""
    controller = await start(hass, mock_config_entry)
    await controller.async_show_clock()
    mock_panel.responder = ignore("clock", mock_panel)

    with pytest.raises(HomeAssistantError) as err:
        await controller.async_set_clock(style=3)

    assert err.value.translation_key == "command_failed"
    assert controller.state.clock.style == 3

    mock_panel.responder = mock_panel.answer
    mock_panel.writes.clear()
    await controller.async_set_brightness(40)
    assert mock_panel.commands == [
        "set_time",
        "orientation 0",
        "clock 3 24h date",
        "brightness 40",
    ]


# Time sync (F6.4 to F6.7)


@pytest.mark.parametrize(
    ("state", "commands"),
    [
        (DisplayState(), ["set_time"]),
        (DisplayState(mode=Mode.CLOCK), ["set_time", CLOCK]),
        # set_time turns the screen on (check V7), showing the clock
        (DisplayState(mode=Mode.CLOCK, power=False), ["set_time", CLOCK]),
    ],
    ids=["unknown mode", "clock", "clock, screen off"],
)
async def test_sync_time(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    state: DisplayState,
    commands: list[str],
) -> None:
    """Sync time sends HA's time and, with the clock, the clock with its date."""
    save_state(hass_storage, mock_config_entry, state)
    controller = await start(hass, mock_config_entry)
    mock_panel.writes.clear()

    await controller.async_sync_time()

    assert mock_panel.commands == commands
    assert mock_panel.screen_on
    assert hass.states.get(POWER).state == STATE_ON


async def test_sync_time_connects(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Like any command, Sync time opens the connection (F3.4)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_disconnect()
    mock_panel.advertise()
    mock_panel.writes.clear()

    await controller.async_sync_time()

    assert mock_panel.connected
    assert mock_panel.commands == [*DEFAULT_RESTORE, "set_time"]


@pytest.mark.parametrize(
    ("state", "commands"),
    [
        (DisplayState(mode=Mode.CLOCK), ["set_time", CLOCK]),
        (DisplayState(), ["set_time"]),
        # Skipped: set_time would turn the screen on (check V7)
        (DisplayState(mode=Mode.CLOCK, power=False), []),
        (DisplayState(power=False), []),
    ],
    ids=["clock", "unknown mode", "clock, screen off", "unknown mode, screen off"],
)
@pytest.mark.freeze_time("2026-11-07 22:59:00+00:00")
async def test_midnight_sync(
    hass: HomeAssistant,
    hass_storage: dict,
    freezer: FrozenDateTimeFactory,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    state: DisplayState,
    commands: list[str],
) -> None:
    """Just after midnight in HA's time zone, the time and the date are synced (F6.6).

    The system is in UTC, where it's still the 7th. A screen that's off is
    left alone.
    """
    await hass.config.async_set_time_zone("Europe/Rome")
    save_state(hass_storage, mock_config_entry, state)
    await start(hass, mock_config_entry)
    screen_on = mock_panel.screen_on
    mock_panel.writes.clear()

    await fire_at(hass, freezer, "2026-11-07 23:00:05+00:00")

    assert mock_panel.commands == commands
    if commands:
        assert panel_time(mock_panel.writes[0]) == "00:00:05"
    if len(commands) > 1:
        assert panel_date(mock_panel.writes[1]) == "08/11/26 7"
    assert mock_panel.screen_on is screen_on


@pytest.mark.freeze_time("2026-10-25 01:30:00+00:00")
async def test_sync_after_daylight_saving_change(
    hass: HomeAssistant,
    hass_storage: dict,
    freezer: FrozenDateTimeFactory,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """At 03:05 the time is synced again, after the clocks went back an hour (F6.5)."""
    await hass.config.async_set_time_zone("Europe/Rome")
    save_state(hass_storage, mock_config_entry, DisplayState(mode=Mode.CLOCK))
    await start(hass, mock_config_entry)
    mock_panel.writes.clear()

    await fire_at(hass, freezer, "2026-10-25 02:05:00+00:00")

    assert mock_panel.commands == ["set_time"]
    assert panel_time(mock_panel.writes[0]) == "03:05:00"


@pytest.mark.freeze_time("2026-11-07 22:59:00+00:00")
async def test_scheduled_syncs_dont_reconnect(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """With Auto reconnect off, a scheduled sync leaves the panel free (F3.4)."""
    await hass.config.async_set_time_zone("Europe/Rome")
    controller = await start(hass, mock_config_entry)
    await controller.async_disconnect()
    mock_panel.advertise()
    attempts = mock_panel.connect_attempts
    mock_panel.writes.clear()

    await fire_at(hass, freezer, "2026-11-07 23:00:05+00:00")
    await fire_at(hass, freezer, "2026-11-08 02:05:00+00:00")

    assert mock_panel.connect_attempts == attempts
    assert mock_panel.writes == []


@pytest.mark.freeze_time("2026-11-07 22:59:00+00:00")
async def test_failed_scheduled_sync_is_logged(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nobody waits for a scheduled sync: a failure is only logged."""
    await hass.config.async_set_time_zone("Europe/Rome")
    await start(hass, mock_config_entry)
    # Frozen time never lets an ACK wait expire: fail the write instead
    mock_panel.write_error = BleakError("write failed")

    await fire_at(hass, freezer, "2026-11-07 23:00:05+00:00")

    assert "Syncing the time of AA:BB:CC:DD:EE:FF failed" in caplog.text


@pytest.mark.freeze_time("2026-11-07 22:59:00+00:00")
async def test_unloading_stops_the_scheduled_syncs(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unloaded display gets nothing on schedule."""
    await start(hass, mock_config_entry)
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_panel.writes.clear()

    await fire_at(hass, freezer, "2026-11-08 08:00:05+00:00")

    assert mock_panel.writes == []


# Reconnection (F3)


async def test_reconnects_on_the_first_advertisement(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The callback runs before HA records the advertisement: wait for it.

    Without the sleep(0) the panel couldn't be looked up yet.
    """
    mock_panel.present = False
    await start(hass, mock_config_entry)
    assert not mock_panel.clients

    mock_panel.advertise()
    await settle(hass)

    assert mock_panel.connected
    assert mock_panel.commands == DEFAULT_RESTORE


async def test_ignores_advertisements_it_cant_connect_through(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """An advertisement heard by a passive scanner doesn't make the panel reachable."""
    mock_panel.present = False
    await start(hass, mock_config_entry)

    mock_panel.advertise(connectable=False)
    await settle(hass)

    assert not mock_panel.clients
    assert hass.states.get(POWER).state == STATE_UNAVAILABLE


async def test_pause_after_a_failed_attempt(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After a failed attempt, advertisements wait 30 s before the next (F3.3)."""
    mock_panel.connect_error = BleakError("no free slot")
    await start(hass, mock_config_entry)
    assert mock_panel.connect_attempts == 1

    mock_panel.advertise()
    await settle(hass)
    assert mock_panel.connect_attempts == 1

    mock_panel.connect_error = None
    freezer.tick(RECONNECT_COOLDOWN + 1)
    mock_panel.advertise()
    await settle(hass)

    assert mock_panel.connect_attempts == 2
    assert mock_panel.connected


async def test_a_command_connects_during_the_pause(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The pause holds back only reconnecting by ourselves."""
    mock_panel.connect_error = BleakError("no free slot")
    controller = await start(hass, mock_config_entry)
    mock_panel.connect_error = None

    await controller.async_set_brightness(40)

    assert mock_panel.connect_attempts == 2
    assert mock_panel.commands == [*DEFAULT_RESTORE, "brightness 40"]


async def test_disconnect_frees_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Disconnect turns off Auto reconnect, so HA doesn't take the panel back (F3.6)."""
    controller = await start(hass, mock_config_entry)

    await controller.async_disconnect()
    mock_panel.advertise()
    await settle(hass)

    assert not mock_panel.connected
    assert not controller.state.auto_reconnect
    assert hass.states.get(AUTO_RECONNECT).state == STATE_OFF
    # Still in range, so a command can take it back
    assert hass.states.get(POWER).state == STATE_ON


async def test_disconnect_stops_a_connection_attempt(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Disconnect doesn't wait for a slow attempt in the background."""

    async def never_connects(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    mock_panel.establish_connection = never_connects
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await mock_config_entry.runtime_data.async_disconnect()

    assert not mock_config_entry.runtime_data.state.auto_reconnect


async def test_command_reconnects_after_disconnect(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """With Auto reconnect off, a command opens the connection (F3.4)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_disconnect()
    mock_panel.advertise()
    mock_panel.writes.clear()

    await controller.async_set_brightness(40)

    assert mock_panel.connected
    assert mock_panel.commands == [*DEFAULT_RESTORE, "brightness 40"]
    assert not controller.state.auto_reconnect


async def test_turning_auto_reconnect_on_reconnects(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Turned back on, Auto reconnect connects at once, even during a pause (F3.5)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_disconnect()
    mock_panel.advertise()
    # A failed command starts the pause
    mock_panel.connect_error = BleakError("no free slot")
    with pytest.raises(HomeAssistantError):
        await controller.async_set_power(False)
    mock_panel.connect_error = None

    await controller.async_set_auto_reconnect(True)
    await settle(hass)

    assert mock_panel.connected
    assert controller.state.auto_reconnect


async def test_auto_reconnect_off_waits_for_a_command(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """With Auto reconnect off, a power cycle leaves the panel alone (F3.4)."""
    controller = await start(hass, mock_config_entry)
    await controller.async_set_auto_reconnect(False)

    mock_panel.lose_power()
    mock_panel.power_on()
    await settle(hass)

    assert not mock_panel.connected
    assert mock_panel.connect_attempts == 1


# Availability (T1, check V4)


async def test_availability_follows_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Controls need the panel connected or advertising; settings don't."""
    await start(hass, mock_config_entry)

    # Connected, the panel doesn't advertise and HA's Bluetooth forgets it
    mock_panel.vanish()
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == STATE_ON

    mock_panel.lose_power()
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == STATE_UNAVAILABLE
    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert hass.states.get(AUTO_RECONNECT).state == STATE_ON
    assert hass.states.get(ORIENTATION).state == "normal"

    mock_panel.power_on()
    await settle(hass)
    assert hass.states.get(POWER).state == STATE_ON
    assert hass.states.get(CONNECTED).state == STATE_ON


async def test_unavailable_once_hass_forgets_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """After a drop, controls stay available until HA's Bluetooth forgets the panel."""
    await start(hass, mock_config_entry)

    mock_panel.lose_power()
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == STATE_ON

    mock_panel.vanish()
    await hass.async_block_till_done()
    assert hass.states.get(POWER).state == STATE_UNAVAILABLE
