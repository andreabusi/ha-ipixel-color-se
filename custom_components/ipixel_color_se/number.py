"""Numbers for iPixel displays."""

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry
from .entity import IPixelEntity
from .state import BRIGHTNESS_MAX, BRIGHTNESS_MIN

PARALLEL_UPDATES = 0

BRIGHTNESS = NumberEntityDescription(
    key="brightness",
    translation_key="brightness",
    native_min_value=BRIGHTNESS_MIN,
    native_max_value=BRIGHTNESS_MAX,
    native_step=1,
    native_unit_of_measurement=PERCENTAGE,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the numbers of a display."""
    async_add_entities([IPixelBrightness(entry.runtime_data, BRIGHTNESS)])


class IPixelBrightness(IPixelEntity, NumberEntity):
    """The brightness of the screen. Unknown until it's first set."""

    @property
    def native_value(self) -> int | None:
        """Return the last brightness the panel accepted."""
        return self.controller.state.brightness

    async def async_set_native_value(self, value: float) -> None:
        """Set the brightness."""
        await self.controller.async_set_brightness(int(value))
