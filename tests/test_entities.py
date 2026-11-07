"""Tests for the entities and the device of a display."""

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipixel_color_se.const import DOMAIN

from .common import ADDRESS, ENTRY_DATA, NAME, FakePanel
from .test_init import setup_entry


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
        "binary_sensor.kitchen_pixel_connected": (
            f"{ADDRESS}_connected",
            EntityCategory.DIAGNOSTIC,
        ),
        "sensor.kitchen_pixel_width": (f"{ADDRESS}_width", EntityCategory.DIAGNOSTIC),
        "sensor.kitchen_pixel_height": (
            f"{ADDRESS}_height",
            EntityCategory.DIAGNOSTIC,
        ),
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
    assert entity_ids == [
        "binary_sensor.kitchen_pixel_connected",
        "binary_sensor.living_room_pixel_connected",
        "sensor.kitchen_pixel_height",
        "sensor.kitchen_pixel_width",
        "sensor.living_room_pixel_height",
        "sensor.living_room_pixel_width",
    ]
