"""Switches for iPixel displays."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry, IPixelController
from .entity import IPixelEntity
from .state import DisplayState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class IPixelSwitchEntityDescription(SwitchEntityDescription):
    """A switch of a display, with how to read and set it."""

    is_on_fn: Callable[[DisplayState], bool]
    set_fn: Callable[[IPixelController, bool], Coroutine[Any, Any, None]]


SWITCHES = (
    IPixelSwitchEntityDescription(
        key="power",
        translation_key="power",
        is_on_fn=lambda state: state.power,
        set_fn=lambda controller, on: controller.async_set_power(on),
    ),
    IPixelSwitchEntityDescription(
        key="clock_24h",
        translation_key="clock_24h",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.clock.format_24h,
        set_fn=lambda controller, on: controller.async_set_clock(format_24h=on),
    ),
    IPixelSwitchEntityDescription(
        key="clock_show_date",
        translation_key="clock_show_date",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.clock.show_date,
        set_fn=lambda controller, on: controller.async_set_clock(show_date=on),
    ),
    IPixelSwitchEntityDescription(
        key="auto_reconnect",
        translation_key="auto_reconnect",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda state: state.auto_reconnect,
        set_fn=lambda controller, on: controller.async_set_auto_reconnect(on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches of a display."""
    async_add_entities(
        IPixelSwitch(entry.runtime_data, description) for description in SWITCHES
    )


class IPixelSwitch(IPixelEntity, SwitchEntity):
    """A switch backed by the controller's desired state."""

    entity_description: IPixelSwitchEntityDescription

    @property
    def is_on(self) -> bool:
        """Return the last state the panel accepted, or the saved setting."""
        return self.entity_description.is_on_fn(self.controller.state)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.entity_description.set_fn(self.controller, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.entity_description.set_fn(self.controller, False)
