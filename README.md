# iPixel Color SE

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=andreabusi&repository=ha-ipixel-color-se&category=integration)

A Home Assistant integration for iPixel Color Bluetooth LED matrix displays, also sold as the "B.K. Light LED Pixel Board".

- Turn the screen on and off, and set its brightness and orientation
- Show a clock, in 8 styles, with the time kept in sync with Home Assistant
- Show animated GIFs and still images from the Media browser, `/local/` or a URL
- Reconnect by itself, and put the display back as it was after a power cut

Showing text isn't supported yet.

## Requirements

- Home Assistant 2026.10.0 or later
- A Bluetooth adapter, or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/), within range of the display

It has been tested on a 32×32 display. Other sizes should work, but the clock styles may look different.

## Installation

### HACS

1. In HACS, open the menu in the top right corner and choose **Custom repositories**.
2. Add `https://github.com/andreabusi/ha-ipixel-color-se` with the type **Integration**.
3. Find **iPixel Color SE** in HACS and download it.
4. Restart Home Assistant.

### Manual

1. Download the latest [release](https://github.com/andreabusi/ha-ipixel-color-se/releases).
2. Copy `custom_components/ipixel_color_se` into the `custom_components` folder of your Home Assistant configuration.
3. Restart Home Assistant.

## Adding a display

Power on the display and make sure the phone app isn't connected to it: the display accepts one connection at a time.

Home Assistant discovers displays in range and offers them under **Settings → Devices & services**. You can also choose **Add integration → iPixel Color SE**, and pick a display from the list or enter its Bluetooth address.

The name you give the display prefixes all its entities: "Kitchen Pixel" gives `switch.kitchen_pixel_power`. The examples below use that name.

## Entities

### Controls

| Entity | Type | What it does |
|---|---|---|
| Power | switch | Turns the screen on and off |
| Brightness | number | 1–100 % |
| Mode | select | What the display shows: `clock` or `image`. `image` shows the last image again |
| Image player | media_player | Shows images. See [Image player](#image-player) |

### Configuration

| Entity | Type | What it does |
|---|---|---|
| Clock style | select | `planet_yellow`, `planet_gradient`, `planet_blue`, `frame_gradient`, `frame_yellow`, `frame_multicolor`, `hourglass_yellow`, `hourglass_orange` |
| Clock 24-hour format | switch | 24-hour or 12-hour time |
| Clock show date | switch | Alternates the date with the time |
| Image fit | select | `fill` or `fit`. See [Fill and Fit](#fill-and-fit) |
| Orientation | select | `normal`, `rotated_counterclockwise`, `upside_down`, `rotated_clockwise` |
| Auto reconnect | switch | See [Reconnection](#reconnection-and-disconnect) |
| Sync time | button | Sends Home Assistant's time now |
| Disconnect | button | Frees the display for the phone app |

A change is sent at once if what it affects is on the screen. A clock style chosen while an image is showing applies the next time the clock appears.

### Diagnostic

| Entity | Type | What it does |
|---|---|---|
| Connected | binary_sensor | On while Home Assistant is connected to the display |
| Width, Height | sensor | The resolution, in pixels |
| Signal strength | sensor | RSSI in dBm. Disabled by default. See [Known limitations](#known-limitations) |

Controls become unavailable when the display can't be reached. Configuration and diagnostic entities stay available.

## Image player

Pick an image from the Media browser, or use `media_player.play_media` in an automation.

| Source | Example |
|---|---|
| Media browser | `media-source://media_source/local/cat.gif` |
| A file in `config/www` | `/local/cat.gif` |
| A URL | `https://example.com/cat.gif` |

- **Formats**: GIF, PNG, JPEG, WebP and BMP. The format is read from the file, whatever its name.
- **Size**: the source file can be up to 10 MB.
- **GIFs** keep their frame timing, and the display loops them by itself.
- **Transparent areas** become black.
- **Play** shows the last image again. **Stop** shows the clock.

Sending an image takes about 5 seconds per 12 KB after it's scaled to the display: small images take about a second, and a 60 KB GIF about 25 seconds. Commands sent in the meantime run as soon as it's done.

Only the source of the last image is remembered, and the image is read again when it needs to be shown. If it can't be read any more when the display comes back, for example because a temporary URL expired, the display shows the clock and Mode changes to `clock`.

### Fill and Fit

- **Fill** (the default) covers the whole screen and crops what doesn't fit.
- **Fit** shows the whole image, with black bars where it doesn't reach the edges.

Changing it sends an image on the screen again with the new fit.

## Automations

Everything uses the standard actions of each entity.

Show a GIF when someone rings, then go back to the clock:

```yaml
automation:
  - alias: "Doorbell on the display"
    triggers:
      - trigger: state
        entity_id: binary_sensor.doorbell
        to: "on"
    actions:
      - action: media_player.play_media
        target:
          entity_id: media_player.kitchen_pixel_image_player
        data:
          media_content_id: media-source://media_source/local/doorbell.gif
          media_content_type: image/gif
      - delay: "00:00:30"
      - action: media_player.media_stop
        target:
          entity_id: media_player.kitchen_pixel_image_player
```

Turn the screen off at night, and back on dimmed in the morning:

```yaml
automation:
  - alias: "Display off at night"
    triggers:
      - trigger: time
        at: "23:00:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.kitchen_pixel_power

  - alias: "Display on in the morning"
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.kitchen_pixel_brightness
        data:
          value: 30
      - action: select.select_option
        target:
          entity_id: select.kitchen_pixel_mode
        data:
          option: clock
```

Brightness, the clock and images all turn the screen back on, and Power follows. An action that fails shows an error and stops the automation.

## Reconnection and Disconnect

Home Assistant stays connected to the display. If the connection drops, usually because the display lost power, it connects again within a few seconds of the display coming back. After a failed attempt it waits 30 seconds.

Every new connection, including the first after Home Assistant starts, puts the display back as it was: time and date, orientation, brightness, and then the screen off if it was off, or the last clock or image. A GIF is sent again each time, so it can take a while to reappear.

- **Auto reconnect** off: Home Assistant doesn't connect by itself. Any command sent to the display connects again.
- **Disconnect** closes the connection and turns off Auto reconnect, so you can use the phone app. To give the display back to Home Assistant, turn on Auto reconnect or send it a command.

## Known limitations

- **One connection at a time.** While Home Assistant is connected, the phone app can't connect. Use Disconnect first.
- **Signal strength updates only while the display is disconnected.** The display stops advertising while it's connected, so the sensor keeps its last known value until the next disconnection.
- **The display doesn't report whether the screen is on, or its brightness.** Home Assistant shows the last state it sent. Changes made in the phone app aren't seen, and the next connection overrides them.
- **Through an ESPHome proxy**, commands are slower, and on a weak WiFi link a command or an image transfer can fail. The error shows in the UI, and the state is restored at the next connection.
- **Some websites refuse Home Assistant's downloads**, for example with `429 Too Many Requests`, even if the image opens in a browser. Save the image in `config/www` or in your media folder instead.
- The display has a ninth clock style that isn't available yet.

## Diagnostics

Open the device, or the integration entry, under **Settings → Devices & services**, and choose **Download diagnostics** from the menu. Please attach the file when you [report a problem](https://github.com/andreabusi/ha-ipixel-color-se/issues).

It holds the display's type, resolution and Bluetooth address, the connection state, the adapter or proxy in use, the signal strength, the desired state of the display and the source of the last image. The query string of an image URL, which may hold a token, is hidden.

For a detailed log, add this to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.ipixel_color_se: debug
```

## Moving from ha-ipixel-color

There's no migration: this is a separate integration with new entities.

1. Note the automations, scripts and dashboards that use the old entities.
2. Remove the display from [ha-ipixel-color](https://github.com/cagcoach/ha-ipixel-color). Home Assistant deletes its entities.
3. Add the display here, and update your automations and dashboards by hand.

The two can be installed together, but both offer the same display when it's discovered, and only one can connect to it. Don't set it up in both.

## Credits

This integration is a simplified rewrite of [ha-ipixel-color](https://github.com/cagcoach/ha-ipixel-color) by cagcoach, and reuses parts of its code under the GPL-3.0.

The display commands are built with [pypixelcolor](https://github.com/lucagoc/pypixelcolor) by lucagoc, licensed under the MIT license.

## License

GPL-3.0. See [LICENSE](LICENSE).
