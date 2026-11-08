"""Tests for the entities and the device of a display."""

import json
from pathlib import Path

from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE, SERVICE_SET_VALUE
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipixel_color_se.const import DOMAIN

from .common import ADDRESS, ENTRY_DATA, NAME, FakePanel
from .test_init import setup_entry

POWER = "switch.kitchen_pixel_power"
BRIGHTNESS = "number.kitchen_pixel_brightness"
ORIENTATION = "select.kitchen_pixel_orientation"
MODE = "select.kitchen_pixel_mode"
IMAGE_PLAYER = "media_player.kitchen_pixel_image_player"
IMAGE_FIT = "select.kitchen_pixel_image_fit"
CLOCK_STYLE = "select.kitchen_pixel_clock_style"
CLOCK_24H = "switch.kitchen_pixel_clock_24_hour_format"
CLOCK_SHOW_DATE = "switch.kitchen_pixel_clock_show_date"
SYNC_TIME = "button.kitchen_pixel_sync_time"
AUTO_RECONNECT = "switch.kitchen_pixel_auto_reconnect"
DISCONNECT = "button.kitchen_pixel_disconnect"
CONNECTED = "binary_sensor.kitchen_pixel_connected"
WIDTH = "sensor.kitchen_pixel_width"
SIGNAL_STRENGTH = "sensor.kitchen_pixel_signal_strength"


async def call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    """Call an entity action and wait for it, as the UI does."""
    await hass.services.async_call(domain, service, data, blocking=True)


async def test_entities_are_prefixed_with_the_display_name(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Each entity declares only its own name: HA adds the display's."""
    await setup_entry(hass, mock_config_entry)

    entities = {
        entry.entity_id: (entry.unique_id, entry.entity_category)
        for entry in er.async_entries_for_config_entry(
            entity_registry, mock_config_entry.entry_id
        )
    }
    assert entities == {
        POWER: (f"{ADDRESS}_power", None),
        BRIGHTNESS: (f"{ADDRESS}_brightness", None),
        MODE: (f"{ADDRESS}_mode", None),
        IMAGE_PLAYER: (f"{ADDRESS}_image_player", None),
        IMAGE_FIT: (f"{ADDRESS}_image_fit", EntityCategory.CONFIG),
        CLOCK_STYLE: (f"{ADDRESS}_clock_style", EntityCategory.CONFIG),
        CLOCK_24H: (f"{ADDRESS}_clock_24h", EntityCategory.CONFIG),
        CLOCK_SHOW_DATE: (f"{ADDRESS}_clock_show_date", EntityCategory.CONFIG),
        SYNC_TIME: (f"{ADDRESS}_sync_time", EntityCategory.CONFIG),
        ORIENTATION: (f"{ADDRESS}_orientation", EntityCategory.CONFIG),
        AUTO_RECONNECT: (f"{ADDRESS}_auto_reconnect", EntityCategory.CONFIG),
        DISCONNECT: (f"{ADDRESS}_disconnect", EntityCategory.CONFIG),
        CONNECTED: (f"{ADDRESS}_connected", EntityCategory.DIAGNOSTIC),
        WIDTH: (f"{ADDRESS}_width", EntityCategory.DIAGNOSTIC),
        "sensor.kitchen_pixel_height": (
            f"{ADDRESS}_height",
            EntityCategory.DIAGNOSTIC,
        ),
        SIGNAL_STRENGTH: (f"{ADDRESS}_signal_strength", EntityCategory.DIAGNOSTIC),
    }
    width = hass.states.get("sensor.kitchen_pixel_width")
    assert width.state == "32"
    assert width.attributes["unit_of_measurement"] == "px"
    assert width.attributes["friendly_name"] == f"{NAME} Width"
    connected = hass.states.get("binary_sensor.kitchen_pixel_connected")
    assert connected.attributes["device_class"] == "connectivity"
    assert connected.attributes["friendly_name"] == f"{NAME} Connected"


async def test_device(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The device has the display's name, its resolution and its address."""
    await setup_entry(hass, mock_config_entry)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, ADDRESS), mock_config_entry.entry_id
    )

    assert device is not None
    assert device.name == NAME
    assert device.manufacturer == "iPixel"
    assert device.model == "LED Pixel Board 32×32"
    assert device.connections == {(dr.CONNECTION_BLUETOOTH, ADDRESS)}


async def test_two_displays(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """With two displays, every entity_id has its display's prefix, none ends in _2."""
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Living Room Pixel",
        unique_id="11:22:33:44:55:66",
        data={**ENTRY_DATA, "address": "11:22:33:44:55:66"},
    )
    await setup_entry(hass, mock_config_entry)
    await setup_entry(hass, other)

    entity_ids = sorted(
        entry.entity_id
        for entry in entity_registry.entities.values()
        if entry.platform == DOMAIN
    )
    assert entity_ids == sorted(
        f"{platform}.{display}_{key}"
        for display in ("kitchen_pixel", "living_room_pixel")
        for platform, key in (
            ("binary_sensor", "connected"),
            ("button", "disconnect"),
            ("button", "sync_time"),
            ("media_player", "image_player"),
            ("number", "brightness"),
            ("select", "clock_style"),
            ("select", "image_fit"),
            ("select", "mode"),
            ("select", "orientation"),
            ("sensor", "height"),
            ("sensor", "signal_strength"),
            ("sensor", "width"),
            ("switch", "auto_reconnect"),
            ("switch", "clock_24_hour_format"),
            ("switch", "clock_show_date"),
            ("switch", "power"),
        )
    )


async def test_power(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Power turns the screen off and on."""
    await setup_entry(hass, mock_config_entry)
    assert hass.states.get(POWER).attributes["friendly_name"] == f"{NAME} Power"
    mock_panel.writes.clear()

    await call(hass, "switch", SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: POWER})
    assert hass.states.get(POWER).state == STATE_OFF
    assert not mock_panel.screen_on

    await call(hass, "switch", SERVICE_TURN_ON, **{ATTR_ENTITY_ID: POWER})
    assert hass.states.get(POWER).state == STATE_ON
    assert mock_panel.commands == ["power off", "power on"]


async def test_brightness(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Brightness is a slider from 1 to 100 %, unknown until it's first set."""
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(BRIGHTNESS)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["min"] == 1
    assert state.attributes["max"] == 100
    assert state.attributes["step"] == 1
    assert state.attributes["mode"] == "slider"
    assert state.attributes["unit_of_measurement"] == "%"
    mock_panel.writes.clear()

    await call(
        hass,
        "number",
        SERVICE_SET_VALUE,
        **{ATTR_ENTITY_ID: BRIGHTNESS, ATTR_VALUE: 40},
    )

    assert hass.states.get(BRIGHTNESS).state == "40"
    assert mock_panel.commands == ["brightness 40"]


async def test_orientation(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Orientation offers the panel's four values and sends them at once."""
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(ORIENTATION)
    assert state.state == "normal"
    assert state.attributes["options"] == [
        "normal",
        "rotated_counterclockwise",
        "upside_down",
        "rotated_clockwise",
    ]
    mock_panel.writes.clear()

    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: ORIENTATION, ATTR_OPTION: "upside_down"},
    )

    assert hass.states.get(ORIENTATION).state == "upside_down"
    assert mock_panel.commands == ["orientation 2"]


async def test_mode(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Mode is unknown until HA shows something (F7.4); Clock shows the clock."""
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(MODE)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["options"] == ["clock", "image"]
    assert state.attributes["friendly_name"] == f"{NAME} Mode"
    mock_panel.writes.clear()

    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: MODE, ATTR_OPTION: "clock"},
    )

    assert hass.states.get(MODE).state == "clock"
    assert mock_panel.commands == ["clock 1 24h date", "set_time"]


async def test_mode_image_without_an_image(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Image needs an image played first: the error says so (F7.2)."""
    await setup_entry(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError) as err:
        await call(
            hass,
            "select",
            SERVICE_SELECT_OPTION,
            **{ATTR_ENTITY_ID: MODE, ATTR_OPTION: "image"},
        )

    assert str(err.value) == (
        f"{NAME} has no image to show yet. Play one with the image player first"
    )
    assert hass.states.get(MODE).state == STATE_UNKNOWN


async def test_image_fit(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Image fit is a setting: Fill by default, or Fit."""
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(IMAGE_FIT)
    assert state.state == "fill"
    assert state.attributes["options"] == ["fill", "fit"]
    assert state.attributes["friendly_name"] == f"{NAME} Image fit"
    mock_panel.writes.clear()

    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: IMAGE_FIT, ATTR_OPTION: "fit"},
    )

    assert hass.states.get(IMAGE_FIT).state == "fit"
    # No image shown: nothing to send again
    assert mock_panel.writes == []


async def test_clock_options(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The clock's options are settings, sent at once while the clock is shown."""
    await setup_entry(hass, mock_config_entry)
    state = hass.states.get(CLOCK_STYLE)
    assert state.state == "planet_yellow"
    assert state.attributes["options"] == [
        "planet_yellow",
        "planet_gradient",
        "planet_blue",
        "frame_gradient",
        "frame_yellow",
        "frame_multicolor",
        "hourglass_yellow",
        "hourglass_orange",
    ]
    assert hass.states.get(CLOCK_24H).state == STATE_ON
    assert hass.states.get(CLOCK_24H).attributes["friendly_name"] == (
        f"{NAME} Clock 24-hour format"
    )
    assert hass.states.get(CLOCK_SHOW_DATE).state == STATE_ON
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: MODE, ATTR_OPTION: "clock"},
    )
    mock_panel.writes.clear()

    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: CLOCK_STYLE, ATTR_OPTION: "hourglass_orange"},
    )
    await call(hass, "switch", SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: CLOCK_24H})
    await call(hass, "switch", SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: CLOCK_SHOW_DATE})

    assert hass.states.get(CLOCK_STYLE).state == "hourglass_orange"
    assert hass.states.get(CLOCK_24H).state == STATE_OFF
    assert hass.states.get(CLOCK_SHOW_DATE).state == STATE_OFF
    assert mock_panel.commands == [
        "clock 8 24h date",
        "clock 8 12h date",
        "clock 8 12h",
    ]


async def test_sync_time(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Sync time sends HA's time."""
    await setup_entry(hass, mock_config_entry)
    mock_panel.writes.clear()

    await call(hass, "button", SERVICE_PRESS, **{ATTR_ENTITY_ID: SYNC_TIME})

    assert mock_panel.commands == ["set_time"]


async def test_disconnect_and_auto_reconnect(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Disconnect turns Auto reconnect off; turning it on connects again."""
    await setup_entry(hass, mock_config_entry)

    await call(hass, "button", SERVICE_PRESS, **{ATTR_ENTITY_ID: DISCONNECT})
    mock_panel.advertise()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CONNECTED).state == STATE_OFF
    assert hass.states.get(AUTO_RECONNECT).state == STATE_OFF

    await call(hass, "switch", SERVICE_TURN_ON, **{ATTR_ENTITY_ID: AUTO_RECONNECT})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CONNECTED).state == STATE_ON
    assert hass.states.get(AUTO_RECONNECT).state == STATE_ON


async def test_failed_action_shows_an_error(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A failed action raises a translated message, for the UI and automations."""
    await setup_entry(hass, mock_config_entry)
    mock_panel.lose_power()

    with pytest.raises(HomeAssistantError) as err:
        await call(
            hass,
            "select",
            SERVICE_SELECT_OPTION,
            **{ATTR_ENTITY_ID: ORIENTATION, ATTR_OPTION: "upside_down"},
        )

    assert str(err.value) == (
        f"Can't connect to {NAME}. Check that it's powered on, in range, and not "
        "connected to the phone app"
    )
    assert hass.states.get(ORIENTATION).state == "normal"


async def test_controls_need_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """Without the panel, controls are unavailable; settings and diagnostics aren't."""
    mock_panel.present = False

    await setup_entry(hass, mock_config_entry)

    for entity_id in (POWER, BRIGHTNESS, MODE, IMAGE_PLAYER):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
    for entity_id in (
        CLOCK_STYLE,
        IMAGE_FIT,
        CLOCK_24H,
        CLOCK_SHOW_DATE,
        SYNC_TIME,
        ORIENTATION,
        AUTO_RECONNECT,
        DISCONNECT,
        CONNECTED,
        WIDTH,
    ):
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE


async def test_signal_strength_is_disabled_by_default(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """It's only useful for checking the range, and rarely changes (check V4)."""
    await setup_entry(hass, mock_config_entry)

    entry = entity_registry.async_get(SIGNAL_STRENGTH)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(SIGNAL_STRENGTH) is None


async def test_signal_strength_when_enabled(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Enabled, it reports the RSSI in dBm, also while disconnected."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{ADDRESS}_signal_strength",
        config_entry=mock_config_entry,
        suggested_object_id="kitchen_pixel_signal_strength",
    )
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(SIGNAL_STRENGTH)
    assert state.state == "-62"
    assert state.attributes["unit_of_measurement"] == "dBm"
    assert state.attributes["device_class"] == "signal_strength"
    assert state.attributes["state_class"] == "measurement"

    await call(hass, "button", SERVICE_PRESS, entity_id=DISCONNECT)
    mock_panel.advertise(rssi=-75)
    await hass.async_block_till_done()

    state = hass.states.get(SIGNAL_STRENGTH)
    assert state.state == "-75"


def test_every_entity_has_an_icon() -> None:
    """icons.json covers every entity that has a name."""
    component = Path(__file__).parent.parent / "custom_components" / DOMAIN
    names = json.loads((component / "translations/en.json").read_text())["entity"]
    icons = json.loads((component / "icons.json").read_text())["entity"]

    assert {platform: sorted(entities) for platform, entities in icons.items()} == {
        platform: sorted(entities) for platform, entities in names.items()
    }
