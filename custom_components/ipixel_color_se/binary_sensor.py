"""Binary sensors for iPixel displays."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry
from .entity import IPixelEntity

PARALLEL_UPDATES = 0

CONNECTED = BinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors of a display."""
    async_add_entities([IPixelConnectedSensor(entry.runtime_data, CONNECTED)])


class IPixelConnectedSensor(IPixelEntity, BinarySensorEntity):
    """On while HA holds the connection to the panel. Always available."""

    @property
    def is_on(self) -> bool:
        """Return whether the panel is connected."""
        return self.controller.connected
