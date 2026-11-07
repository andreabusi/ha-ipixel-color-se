"""Buttons for iPixel displays."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry, IPixelController
from .entity import IPixelEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IPixelButtonEntityDescription(ButtonEntityDescription):
    """A button of a display, with what it does."""

    press_fn: Callable[[IPixelController], Coroutine[Any, Any, None]]


BUTTONS = (
    IPixelButtonEntityDescription(
        key="sync_time",
        translation_key="sync_time",
        entity_category=EntityCategory.CONFIG,
        # Connects if needed, like any command (F6.7)
        press_fn=lambda controller: controller.async_sync_time(),
    ),
    IPixelButtonEntityDescription(
        key="disconnect",
        translation_key="disconnect",
        entity_category=EntityCategory.CONFIG,
        # Frees the panel for the phone app, and stops reconnecting (F3.6)
        press_fn=lambda controller: controller.async_disconnect(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons of a display."""
    async_add_entities(
        IPixelButton(entry.runtime_data, description) for description in BUTTONS
    )


class IPixelButton(IPixelEntity, ButtonEntity):
    """A button that runs an action of the controller."""

    entity_description: IPixelButtonEntityDescription

    async def async_press(self) -> None:
        """Run the action."""
        await self.entity_description.press_fn(self.controller)
