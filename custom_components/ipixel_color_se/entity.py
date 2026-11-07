"""Base entity for iPixel displays."""

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN, MANUFACTURER
from .controller import IPixelController


class IPixelEntity(Entity):
    """An entity of an iPixel display: a thin view of its controller.

    HA prefixes the entity name with the device name, which is the name given
    in the config flow, so entity_ids look like sensor.<display>_<key>.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, controller: IPixelController, description: EntityDescription
    ) -> None:
        """Set up the entity for a controller."""
        self.entity_description = description
        self.controller = controller
        address = controller.address
        panel = controller.panel
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            manufacturer=MANUFACTURER,
            model=f"LED Pixel Board {panel.width}×{panel.height}",
            name=controller.entry.title,
        )

    async def async_added_to_hass(self) -> None:
        """Follow the controller's changes."""
        self.async_on_remove(
            self.controller.async_add_listener(self.async_write_ha_state)
        )
