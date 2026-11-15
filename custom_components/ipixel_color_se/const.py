"""Constants for the iPixel Color SE integration."""

from typing import Final

DOMAIN: Final = "ipixel_color_se"

# Config entry data, besides CONF_ADDRESS. Read once by the config flow.
CONF_DEVICE_TYPE: Final = "device_type"
CONF_WIDTH: Final = "width"
CONF_HEIGHT: Final = "height"
# From the advertisement, when the panel has one: written when it changes
CONF_PRODUCT_ID: Final = "product_id"

# Discovery, kept in sync with the bluetooth matchers in manifest.json. The
# panels seen so far advertise their name and the vendor's manufacturer
# data, no service UUID.
LOCAL_NAME_PREFIX: Final = "LED_BLE_"
SERVICE_UUID: Final = "0000fa01-0000-1000-8000-00805f9b34fb"
MANUFACTURER_ID: Final = 21076  # 0x5254
MANUFACTURER_DATA_START: Final = bytes([0x00, 0x72])  # [0, 114] in the manifest

# GATT characteristics, in the panel's 000000fa service
WRITE_UUID: Final = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID: Final = "0000fa03-0000-1000-8000-00805f9b34fb"

MANUFACTURER: Final = "iPixel"
