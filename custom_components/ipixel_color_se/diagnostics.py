"""Diagnostics for iPixel displays."""

from datetime import datetime
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothReachabilityIntent,
    async_address_reachability_diagnostics,
    async_last_service_info,
)
from homeassistant.core import HomeAssistant

from .controller import IPixelConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IPixelConfigEntry
) -> dict[str, Any]:
    """Return what helps to understand a display's problems."""
    controller = entry.runtime_data
    address = controller.address
    # connectable=False also returns advertisements heard by passive scanners
    service_info = async_last_service_info(hass, address, connectable=False)
    return {
        "entry": {"title": entry.title, "data": dict(entry.data)},
        "connection": {
            "connected": controller.connected,
            "last_connected": _isoformat(controller.last_connected),
            "last_disconnected": _isoformat(controller.last_disconnected),
            "last_error": controller.last_error,
        },
        "bluetooth": {
            "last_advertisement": service_info
            and {
                "name": service_info.name,
                "rssi": service_info.rssi,
                "source": service_info.source,
                "connectable": service_info.connectable,
                "manufacturer_data": {
                    str(company): data.hex(" ")
                    for company, data in service_info.manufacturer_data.items()
                },
                "service_uuids": service_info.service_uuids,
            },
            "reachability": async_address_reachability_diagnostics(
                hass, address, BluetoothReachabilityIntent.CONNECTION
            ),
        },
    }


def _isoformat(value: datetime | None) -> str | None:
    """Return a datetime as ISO 8601, or None."""
    return value.isoformat() if value else None
