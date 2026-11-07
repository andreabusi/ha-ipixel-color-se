# iPixel Color SE

A Home Assistant integration for iPixel Color Bluetooth LED matrix displays, also sold as the "B.K. Light LED Pixel Board".

> [!WARNING]
> **In development.** This version is only the project skeleton: Home Assistant loads the integration, but it can't add a display yet.

## Planned for the first release

- Discovery of displays over Bluetooth, directly or through an ESPHome Bluetooth proxy
- Screen power and brightness
- Clock, in 9 styles, with the time synchronized from Home Assistant
- Images and animated GIFs from the media browser, `/local/` or a URL
- Display orientation
- Automatic reconnection, which you can turn off, and a Disconnect button that frees the display for the phone app
- Connection sensor and diagnostics

Showing text will come in a later release.

## Requirements

- Home Assistant 2026.10.0 or later
- A Bluetooth adapter or proxy within range of the display

The display accepts a single Bluetooth connection. Don't set it up in this integration and in [ha-ipixel-color](https://github.com/cagcoach/ha-ipixel-color) at the same time.

## Credits

This integration is a simplified rewrite of [ha-ipixel-color](https://github.com/cagcoach/ha-ipixel-color) by cagcoach, and reuses parts of its code under the GPL-3.0.

The display commands are built with [pypixelcolor](https://github.com/lucagoc/pypixelcolor) by lucagoc, licensed under the MIT license.

## License

GPL-3.0. See [LICENSE](LICENSE).
