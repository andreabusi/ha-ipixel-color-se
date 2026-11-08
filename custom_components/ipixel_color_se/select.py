"""Selects for iPixel displays."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry, IPixelController
from .entity import IPixelEntity
from .state import DisplayState, ImageFit, Mode

PARALLEL_UPDATES = 0

# What the panel can be asked to show
MODE_OPTIONS = [Mode.CLOCK.value, Mode.IMAGE.value]

# The clock styles, values 1 to 8, named after their time screen on a 32×32
# panel; the date screen is the same for all (check V5). Other models may draw
# them differently. The Store keeps the number, so renaming an option doesn't
# change saved states.
CLOCK_STYLES = {
    1: "planet_yellow",
    2: "planet_gradient",
    3: "planet_blue",
    4: "frame_gradient",
    5: "frame_yellow",
    6: "frame_multicolor",
    7: "hourglass_yellow",
    8: "hourglass_orange",
}
CLOCK_STYLE_VALUES = {option: style for style, option in CLOCK_STYLES.items()}

# The panel's orientation values, 0 to 3, by position: how the content is
# turned (check V8). The Store keeps the number too.
ORIENTATION_OPTIONS = [
    "normal",
    "rotated_counterclockwise",
    "upside_down",
    "rotated_clockwise",
]


@dataclass(frozen=True, kw_only=True)
class IPixelSelectEntityDescription(SelectEntityDescription):
    """A select of a display, with how to read and set it."""

    current_fn: Callable[[DisplayState], str | None]
    select_fn: Callable[[IPixelController, str], Coroutine[Any, Any, None]]


SELECTS = (
    IPixelSelectEntityDescription(
        key="mode",
        translation_key="mode",
        options=MODE_OPTIONS,
        # Unknown until HA shows something (F7.4)
        current_fn=lambda state: state.mode and state.mode.value,
        # Image shows the last image again, or fails if there's none (F7.2)
        select_fn=lambda controller, option: (
            controller.async_show_image()
            if option == Mode.IMAGE
            else controller.async_show_clock()
        ),
    ),
    IPixelSelectEntityDescription(
        key="clock_style",
        translation_key="clock_style",
        entity_category=EntityCategory.CONFIG,
        options=list(CLOCK_STYLES.values()),
        current_fn=lambda state: CLOCK_STYLES[state.clock.style],
        select_fn=lambda controller, option: controller.async_set_clock(
            style=CLOCK_STYLE_VALUES[option]
        ),
    ),
    IPixelSelectEntityDescription(
        key="image_fit",
        translation_key="image_fit",
        entity_category=EntityCategory.CONFIG,
        options=[fit.value for fit in ImageFit],
        current_fn=lambda state: state.image_fit.value,
        # Sent again only while the image is shown (D10)
        select_fn=lambda controller, option: controller.async_set_image_fit(
            ImageFit(option)
        ),
    ),
    IPixelSelectEntityDescription(
        key="orientation",
        translation_key="orientation",
        entity_category=EntityCategory.CONFIG,
        options=ORIENTATION_OPTIONS,
        current_fn=lambda state: ORIENTATION_OPTIONS[state.orientation],
        # Applied whatever the panel shows (F11.2)
        select_fn=lambda controller, option: controller.async_set_orientation(
            ORIENTATION_OPTIONS.index(option)
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the selects of a display."""
    async_add_entities(
        IPixelSelect(entry.runtime_data, description) for description in SELECTS
    )


class IPixelSelect(IPixelEntity, SelectEntity):
    """A select backed by the controller's desired state."""

    entity_description: IPixelSelectEntityDescription

    @property
    def current_option(self) -> str | None:
        """Return the last option the panel accepted, or the saved setting."""
        return self.entity_description.current_fn(self.controller.state)

    async def async_select_option(self, option: str) -> None:
        """Choose an option."""
        await self.entity_description.select_fn(self.controller, option)
