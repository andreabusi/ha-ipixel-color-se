"""Selects for iPixel displays."""

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry
from .entity import IPixelEntity

PARALLEL_UPDATES = 0

# The panel's orientation values, 0 to 3, by position: how the content is
# turned (check V8). The Store keeps the number, so renaming an option
# doesn't change saved states.
ORIENTATION_OPTIONS = [
    "normal",
    "rotated_counterclockwise",
    "upside_down",
    "rotated_clockwise",
]

ORIENTATION = SelectEntityDescription(
    key="orientation",
    translation_key="orientation",
    entity_category=EntityCategory.CONFIG,
    options=ORIENTATION_OPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects of a display."""
    async_add_entities([IPixelOrientation(entry.runtime_data, ORIENTATION)])


class IPixelOrientation(IPixelEntity, SelectEntity):
    """The orientation of the display, applied whatever it shows (F11.2)."""

    @property
    def current_option(self) -> str:
        """Return the last orientation the panel accepted."""
        return ORIENTATION_OPTIONS[self.controller.state.orientation]

    async def async_select_option(self, option: str) -> None:
        """Set the orientation."""
        await self.controller.async_set_orientation(ORIENTATION_OPTIONS.index(option))
