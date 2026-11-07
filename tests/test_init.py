"""Tests for setting up and unloading a display."""

import asyncio

from bleak.exc import BleakError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import FakePanel

CONNECTED = "binary_sensor.kitchen_pixel_connected"
WIDTH = "sensor.kitchen_pixel_width"


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up a display and wait for its first connection attempt."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_setup_connects(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A display in range is connected after setup, with its dependencies."""
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert {"bluetooth_adapters", "media_source"} <= hass.config.components
    assert mock_panel.connected
    assert hass.states.get(CONNECTED).state == STATE_ON
    # Connecting alone sends nothing: the restore arrives with the controller
    assert mock_panel.writes == []


async def test_setup_without_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """HA starts fine while the panel is off, and the fixed data is still there."""
    mock_panel.present = False

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert not mock_panel.clients
    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert hass.states.get(WIDTH).state == "32"


async def test_setup_when_connecting_fails(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A failed first connection doesn't fail the setup, and is recorded."""
    mock_panel.connect_error = BleakError("no free slot")

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert "no free slot" in mock_config_entry.runtime_data.last_error


async def test_unload_frees_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Unloading (or disabling) the entry closes the connection."""
    await setup_entry(hass, mock_config_entry)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert not mock_panel.connected


async def test_unload_while_connecting(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Unloading during a slow connection attempt doesn't wait for it."""

    async def never_connects(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    mock_panel.establish_connection = never_connects
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_dropped_connection(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Connected follows a drop at once, and the drop is logged as a warning."""
    await setup_entry(hass, mock_config_entry)

    mock_panel.client.drop()
    await hass.async_block_till_done()

    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert "Lost the connection to AA:BB:CC:DD:EE:FF" in caplog.text


async def test_ha_stop_frees_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """When HA stops, the connection is closed so the panel is free again."""
    await setup_entry(hass, mock_config_entry)

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert not mock_panel.connected
