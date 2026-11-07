"""Buttons for iPixel displays."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry
from .entity import IPixelEntity

PARALLEL_UPDATES = 0

DISCONNECT = ButtonEntityDescription(
    key="disconnect",
    translation_key="disconnect",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the buttons of a display."""
    async_add_entities([IPixelDisconnectButton(entry.runtime_data, DISCONNECT)])


class IPixelDisconnectButton(IPixelEntity, ButtonEntity):
    """Free the panel for the phone app, and stop reconnecting (F3.6)."""

    async def async_press(self) -> None:
        """Disconnect."""
        await self.controller.async_disconnect()
