"""Constants for the iPixel Color SE integration."""

from typing import Final

DOMAIN: Final = "ipixel_color_se"

# Config entry data, besides CONF_ADDRESS. Read once by the config flow.
CONF_DEVICE_TYPE: Final = "device_type"
CONF_WIDTH: Final = "width"
CONF_HEIGHT: Final = "height"

# Discovery, kept in sync with the bluetooth matchers in manifest.json. The
# panels seen so far advertise only their name, no service UUID.
LOCAL_NAME_PREFIX: Final = "LED_BLE_"
SERVICE_UUID: Final = "0000fa01-0000-1000-8000-00805f9b34fb"

# GATT characteristics, in the panel's 000000fa service
WRITE_UUID: Final = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID: Final = "0000fa03-0000-1000-8000-00805f9b34fb"

MANUFACTURER: Final = "iPixel"
