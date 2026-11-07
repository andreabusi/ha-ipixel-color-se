"""The iPixel Color SE integration."""

from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant

from .controller import IPixelConfigEntry, IPixelController

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: IPixelConfigEntry) -> bool:
    """Set up a display. Never waits for the panel: it may be off."""
    controller = IPixelController(hass, entry)
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_stop(_event: Event) -> None:
        """Free the panel when HA stops."""
        await controller.async_stop()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop)
    )
    controller.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IPixelConfigEntry) -> bool:
    """Unload a display and close its connection, freeing the panel."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unload_ok
