"""Sensors for iPixel displays."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry, IPixelController
from .entity import IPixelEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IPixelSensorEntityDescription(SensorEntityDescription):
    """A sensor of a display, with how to read its value."""

    value_fn: Callable[[IPixelController], int | None]


SENSORS = (
    # Read once by the config flow: available even while disconnected
    IPixelSensorEntityDescription(
        key="width",
        translation_key="width",
        native_unit_of_measurement="px",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda controller: controller.panel.width,
    ),
    IPixelSensorEntityDescription(
        key="height",
        translation_key="height",
        native_unit_of_measurement="px",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda controller: controller.panel.height,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of a display."""
    async_add_entities(
        IPixelSensor(entry.runtime_data, description) for description in SENSORS
    )


class IPixelSensor(IPixelEntity, SensorEntity):
    """A sensor whose value comes from the controller."""

    entity_description: IPixelSensorEntityDescription

    @property
    def native_value(self) -> int | None:
        """Return the sensor's value."""
        return self.entity_description.value_fn(self.controller)
