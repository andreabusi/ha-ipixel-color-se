# iPixel Color SE: technical plan (01-base)

| | |
|---|---|
| **Status** | Done |
| **Date** | 2026-11-08 |
| **Release** | `v0.1.0` |
| **Input** | [spec.md](spec.md) v1.1 (the F*n* and T*n* references point there, the V*n* ones to [panel-checks.md](../panel-checks.md)) |
| **Domain** | `ipixel_color_se` |
| **Repository** | https://github.com/andreabusi/ha-ipixel-color-se (codeowner `@andreabusi`) |

This document describes **how** to build the spec: architecture, modules, flows, tests and order of work. It was written in Italian and translated on 2026-11-13. The only change in content is that the outcomes of the panel checks moved to `panel-checks.md`.

---

## Summary

- **Four-layer architecture**:
  - **entities** are thin views with no logic;
  - one **controller** per display holds the desired state, the rules and the reconnection;
  - our own **Bluetooth transport** goes through HA's stack, so it also works with proxies;
  - a **protocol** module isolates pypixelcolor, which we use only to build commands.
- **A single source of truth**: the desired state lives in the controller and is saved in one file per display (HA's `Store`). Entities no longer read each other's state, as they did in the reference.
- **Reconnection**: based on `bluetooth.async_register_advertisement_callback`, checked in HA 2026.10's code: it receives every advertisement, even one identical to the previous.
- **Automated tests** with `pytest-homeassistant-custom-component` on HA 2026.10.0. The GitHub CI also runs hassfest and the HACS validation.
- **Six milestones** (§12), each installable and testable on the maintainer's HA. The panel checks (V1–V12) are spread over the milestones that need them.

---

## 1. Verified technical constraints

Values read from HA's source code at tag `2026.10.0` and from the pypixelcolor 0.5.0 package.

| Item | Value | Consequence |
|---|---|---|
| Python required by HA 2026.10 | 3.14 | Development environment and CI on Python 3.14 |
| Bleak / bleak-retry-connector / habluetooth | 3.0.2 / 4.7.1 / 7.1.2, shipped with HA | Not listed in the manifest's `requirements` |
| pypixelcolor | 0.5.0, MIT license, depends on `bleak`, `crccheck`, `pillow` without pinned versions | Only `pypixelcolor==0.5.0` in the manifest: an exact pin, because we use internal modules |
| pypixelcolor's `set_clock_mode` | Accepts styles 0–8 | The panel shows styles 1–9 and ignores 0 (V5): we use 1–8. The 9th will come with a pypixelcolor PR and a pin update. |
| pypixelcolor's transport | Creates its own `BleakClient` from the address | Doesn't go through HA's proxies: we use pypixelcolor only to build commands, and the transport is ours |
| `async_register_advertisement_callback` | Exists. Receives every packet, once per scanner that hears it, before HA records it | No replay at startup: the first connection attempt must be made explicitly. Needs an `await asyncio.sleep(0)` before connecting, as in the reference. RSSI updates must be throttled. |
| `async_track_unavailable`, `async_address_present` | Available | Reachability computation (T1) |
| `async_address_reachability_diagnostics(…, BluetoothReachabilityIntent.CONNECTION)` | Available, returns an explanatory text | To be included in the diagnostics (F10.4) |
| entity_id generation | English name, preceded by the device name and, if the device already has an area when the entities are created, by the area | Explains `binary_sensor.taverna_pixel_led_display_connected` in the reference. We don't set a suggested area, so the ids stay `<device>_<entity>` as in §6 of the spec. |
| `media_source.PlayMedia` | Has `url`, `mime_type` and `path` | Local files are read from disk, without going through HTTP |
| `MediaPlayerState.BUFFERING` | Exists | F8.5 |
| Brand icons | The loader recognizes a `brand/` folder in the integration. The `brands` component serves only `icon.png`, `logo.png`, the `@2x` variants and the `dark_` variants, without checking sizes, and falls back to `icon.png` for missing ones | `icon.png` (256×256) and `icon@2x.png` (512×512) are enough, with the sizes of the `home-assistant/brands` repository. The HACS `brands` validation looks for `brand/icon.png` in the repository tree (M5) |
| Test library | `pytest-homeassistant-custom-component==0.13.371` uses `homeassistant==2026.10.0` | Tests run on the minimum supported version |

---

## 2. Architecture

```
 entities (switch, number, select, media_player, button, binary_sensor, sensor)
        │  call methods on the controller and listen to it
        ▼
 IPixelController ── desired state (DisplayState) ── Store (.storage)
        │  rules, reconnection, restore, time scheduling
        ├── image_source      resolves, downloads and validates images
        ▼
 protocol             builds commands (SendPlan) with pypixelcolor
        ▼
 IPixelConnection     HA Bluetooth + bleak-retry-connector, ACKs, responses, lock
```

| Module | Responsibility | Depends on HA? |
|---|---|---|
| `protocol.py` | The only module that imports pypixelcolor. Pure functions that return a `SendPlan`: `power(on)`, `brightness(level)`, `orientation(value)`, `clock_mode(style, format_24h, show_date, now)`, `set_time(now)`, `image(data, fit, width, height)`. It also decodes the panel info. | No |
| `connection.py` | `IPixelConnection`: connection, disconnection, sending a `SendPlan` and waiting for the ACKs, request and response, connection change notifications | Yes (Bluetooth) |
| `state.py` | `DisplayState` and `ClockSettings` dataclasses, `Mode` and `ImageFit` enums, (de)serialization, defaults | No |
| `controller.py` | `IPixelController`: owns the connection, the state and the Store. Exposes the actions the entities call, applies the state rules, handles reconnection, reachability, restore and time sync, and notifies the entities of changes | Yes |
| `image_source.py` | Turns a `media_id` (URL, `/local/…`, `media-source://…`) into bytes, format and title. Applies the 10 MB limit and the format validation | Yes |
| `entity.py` | `IPixelEntity` base class: `has_entity_name`, `unique_id`, `device_info`, availability, controller listener | Yes |
| platforms | One per entity type, defined with `EntityDescription` | Yes |
| `config_flow.py` | Discovery, manual choice, name, connection check | Yes |
| `diagnostics.py` | Download diagnostics | Yes |

**Why a controller and not a `DataUpdateCoordinator`**: there's nothing to poll (T4). HA's coordinator is designed for polling, while here we need a desired state, rules and a sequence of commands. Entities register with `controller.async_add_listener(callback)` and write their state when the controller notifies them.

---

## 3. State and persistence

The controller holds the **desired state**: what HA has decided the panel should show. It's saved with `homeassistant.helpers.storage.Store` (key `ipixel_color_se.<entry_id>`, version 1, 1 s delayed save). So instead of a `RestoreEntity` on every entity there's a single consistent file.

```python
@dataclass
class DisplayState:
    power: bool = True
    brightness: int | None = None        # None = never set: not sent
    orientation: int = 0
    mode: Mode | None = None             # None = unknown: the content isn't restored
    clock: ClockSettings = ClockSettings(style=1, format_24h=True, show_date=True)  # styles 1–8 (V5)
    image_fit: ImageFit = ImageFit.FILL
    image: ImageRef | None = None        # original media_id + title, not the signed URL
    auto_reconnect: bool = True
```

- The `None` values keep the integration from changing the panel's brightness or content on the first install without the user asking.
- When the integration is removed, `async_remove_entry` deletes the file.
- **Fixed data** (address, name, type, width, height) is in `entry.data`, written by the config flow (F1.5), not in the Store.

---

## 4. Connection and reconnection

### 4.1 `IPixelConnection`

- **Connection**: `async_ble_device_from_address(connectable=True)` followed by `establish_connection(BleakClientWithServiceCache, …, ble_device_callback=…)`. With `ble_device_callback`, later attempts use the latest device, for example if the proxy changed meanwhile. After connecting, notifications are enabled **only once**.
- **A single notification handler** routes each frame to the operation in progress: an ACK event or a response future. The reference instead stopped and restarted notifications for every command, which costs more network round trips through proxies.
- **When the connection drops, the dropped client is closed** with `disconnect()`. Seen in M2 on the local adapter: bleak keeps the dropped client's D-Bus connection open, BlueZ restores its notification session on the next connection, and every frame arrives once more for each dropped connection. Closing the client removes the session.
- **`async_send(plan)`**: under an `asyncio.Lock`, which serves requests in order of arrival (F3.1, F8.10).
  - For each window of the plan it writes 244-byte chunks (`response=True`).
  - If the plan's policy requires it, it waits for the ACK `05 00 xx xx <status>`: `0` or `1` for the window, `3` for the end. The timeout is 8 s.
  - It's the same semantics as pypixelcolor's transport, applied uniformly to **all** commands. Confirmed by V9: simple commands get an ACK in about 30 ms, sometimes before the write is confirmed, so the wait is armed before writing.
  - Exception: **`set_time`** doesn't get an ACK but the panel info frame, because it's the same command. That's why `protocol.set_time` is a request with a response.
- **`async_request(plan)`**: sends and returns the first response frame. Used for the panel info.
- **State callbacks**: `on_connected` and `on_disconnected(expected: bool)`. The flag tells a deliberate `Disconnect` from a dropped connection.

### 4.2 Reachability and reconnection in the controller

| Event | Action |
|---|---|
| Advertisement received (`async_register_advertisement_callback`) | Only if connectable: `reachable = True`, update the RSSI (at most one write every 30 s, see below). If not connected, `auto_reconnect` is on, reconnection isn't paused and no attempt is in progress, start the reconnection in the background. |
| `async_track_unavailable` | `reachable = False` |
| Disconnection, deliberate or not | `reachable = async_address_present(…)`: while connected the panel wasn't advertising (V4), so the Bluetooth manager may have already forgotten it |
| Failed attempt, in the background or from a command | 30 s pause (F3.3) for background attempts only: a command connects anyway |
| User command with the panel disconnected | On-demand connection (F3.4). If it fails, `not_reachable` error |
| `Auto reconnect` turned back on | If the panel is present, immediate attempt (F3.5) |
| `Disconnect` | `auto_reconnect = False` (saved), then deliberate disconnection (F3.6) |
| Entry setup | No blocking connection (fixes P5): if `auto_reconnect` is on and the panel is present, an explicit first attempt in the background |

**`Signal strength`** (F10.3):
- **Write limit**: at most one write every 30 s, with the strongest value heard in the interval. The first planned rule, "or if it changes by at least 3 dBm", was tried on the panel and dropped: the RSSI swings by 5–6 dBm from one advertisement to the next (−67/−72), so it wrote about twice a second.
- **Which scanner counts**: the callback fires once for each scanner that hears the panel. The strongest of the interval counts, whichever scanner heard it: it's the path HA would choose to connect. Non-connectable scanners don't count.
- **While connected**: the last known value stays, the one from just before connecting. The panel doesn't advertise (V4), and with `unknown` the sensor would almost never have a value, while its purpose is precisely to show whether the panel is at the edge of range.
- **At HA startup** the initial value comes from HA's Bluetooth history (`async_last_service_info`): the callback doesn't replay, and the panel stops advertising as soon as it's connected.

The availability of control entities is `connected or reachable` (T1): while connected only the connection counts, because the Bluetooth manager eventually forgets a panel that doesn't advertise (V4). `Connected` and the configuration and diagnostic entities are always available: the rule is based on the entity category.

### 4.3 Restore (F9)

On **every** successful connection, including the first after HA starts, the controller runs under its operation lock:

1. `set_time(now)` with HA's time: without power the panel loses time and date (V3);
2. `orientation`;
3. `brightness`, if set;
4. if `power` is false, it sends the screen-off command and stops;
5. otherwise it shows the content again: `Clock` sends the clock command, which turns the screen back on and sets the date again; `Image` downloads the image again and, if it's no longer reachable, shows the clock and sets `mode` to `Clock` (F9.4); if `mode` is `None` it sends power on.

The order matters: `set_time`, orientation and brightness turn the screen back on (V1, V7), so the screen-off command must come after them. With the screen off the panel stays without a date until it's turned back on: turning it on sends `set_time` and the clock (§5). With the screen off the image isn't sent: turning the screen on sends it, because the panel didn't receive it on this connection (§5).

The restore always reapplies the complete state, even after a simple HA restart. That's deliberate: HA can't know whether the panel lost power meanwhile. So a GIF is retransmitted on every HA start (§13).

**Image during HA startup**: media sources and HA URLs may not work until HA has finished starting. In that case step 5 sends only power on, and the image follows with a background task registered with `async_at_started`. The task takes the lock like any command. The restore doesn't wait for startup while holding the lock, because an automation that sends a command to the panel at startup would stay blocked.

If the restore fails (a missing ACK with the connection still open), the controller logs a warning and repeats it before the next command: a command never reaches a panel that hasn't been restored.

---

## 5. Main flows

**Simple command** (`Power`, `Brightness`, `Orientation`):
1. the entity calls the controller;
2. the controller takes the operation lock, connects if needed and sends;
3. if the send succeeds, it updates the state, saves and notifies the entities;
4. if it fails, it raises a translated error (T2) and the state doesn't change.

**`Power`**: turning off sends the screen-off command. Turning on shows the content again:
- with `mode == Clock` it sends `set_time` and the clock command, so the panel gets the time, the date and the options changed while the screen was off;
- with `mode == Image` it sends only power on if the panel has already received that image, with that fit, on the current connection: it keeps it in memory even with the screen off (V11). Otherwise, for example after a power cut, it reads the image again and resends it, and the image itself turns the screen back on;
- otherwise it sends power on.

The controller remembers the image sent on the current connection as a (`media_id`, `image_fit`) pair. It forgets it on every new connection, when it shows the clock and when a transfer starts, because an interrupted transfer can leave anything on the panel.

**Waking the content**: brightness and orientation turn the screen back on (V1) with whatever the panel had. If the screen was off, after the command the controller:
- with `mode == Clock` also sends `set_time` and the clock command, because the panel's clock may have an old time, date or options;
- with `mode == Image` resends the image only if the panel didn't receive it on the current connection, otherwise it would show the built-in GIFs. If it did receive it, the panel already shows it by itself (V11).

**Falling back to the clock**: when the image must be shown again without the user asking for it, that is in the restore, when `Power` turns the screen on and when brightness or orientation wake it, and the source can no longer be read, the controller shows the clock, sets `mode` to `Clock` and logs a warning. The screen comes on as requested (F9.4). The actions that ask for the image itself (`play_media`, Play, `Mode = Image`, `Image fit`) fail instead with a visible error (F8.7). A panel error, that is a missing ACK or a failed write, is still an error.

**Immediate send rule (F6.3, D10)**:
- a change to `ClockSettings` always updates and saves the state, but sends the clock command only if `mode == Clock`, `power` is true and the panel is connected. It doesn't open a connection: with the panel unreachable the option stays saved and the restore applies it on the next connection. If the send fails the error appears, the option stays saved and the restore is repeated before the next command;
- `Image fit` follows the same rule: it reads and resends the image only if `mode == Image`, `power` is true, the panel is connected and doesn't already have the image with that fit;
- `Orientation` is always sent (F11.2).

**Transfers (F8.10)**: a transfer holds the operation lock from start to end. A command that arrives meanwhile waits for the lock and starts right after the last ACK. Checked on the panel: a brightness change requested halfway through a 24 s GIF started 3 ms after the final ACK.

**Power state rule (F5.3, F5.4)**: every successful send of content, brightness, orientation or `set_time` sets `power = True`, because they all turn the screen back on (V1, V7).

**`Mode`**:
- `Clock`: clock command followed by `set_time`;
- `Image`: downloads and sends the image again (`image_source` + `protocol.image`), or a validation error if there's no image (F7.2).

**Image player, `play_media`**:
1. **buffering** state;
2. resolving the source;
3. sending;
4. `image` and `mode` are updated, **playing** state. On error the player goes back to its previous state and shows an error.

Stop is `Mode = Clock`. The player state is derived from the controller: buffering while an image is read, converted or transmitted, in the restore too; playing if `mode == Image` and the screen is on; idle otherwise. After a Stop, the title and `media_content_id` stay those of the last image, which Play sends again.

**Time sync (F6.5, F6.6)**:
- `async_track_time_change` at 00:00:05 syncs the time and, if `mode == Clock`, resends the clock command with the new date. The panel advances the date by itself (V3), so this is only a safeguard;
- at 03:05:00 it syncs again, to cover European daylight saving changes;
- both act only if connected: with `Auto reconnect` off they don't reopen the connection;
- both skip a screen that's off, because `set_time` would turn it back on (V7): time and date arrive when the screen is turned on;
- an error only goes to the log, as a warning, because no user action is in progress.

**`Sync time`** (F6.7): connects if needed, sends `set_time` and, if `mode == Clock`, the clock command with today's date. It sets `power` to true, because `set_time` turns the screen back on (V7).

With an image on screen, `set_time` doesn't replace it with the clock (V12). So scheduled syncs and `Sync time` with `mode == Image` send only `set_time`.

The time always comes from `homeassistant.util.dt.now()` (F6.4).

---

## 6. Entities

`IPixelEntity` base class:
- `_attr_has_entity_name = True`, `translation_key = key`;
- `unique_id = f"{address}_{key}"`;
- `device_info` with `identifiers={(DOMAIN, address)}`, `connections={(CONNECTION_BLUETOOTH, address)}`, `manufacturer="iPixel"` and `model=f"LED Pixel Board {w}×{h}"`.

All strings are in `translations/en.json`, the only strings file: there's no separate `strings.json`, so it can't diverge as in the reference (P9). Icons are in `icons.json`.

| key | Platform | Category | Notes |
|---|---|---|---|
| `power` | switch | — | `controller.state.power` |
| `brightness` | number | — | Slider 1–100 %: 0 doesn't turn the screen off and gives the same minimal light as 1 (V6). State `None` → unknown |
| `mode` | select | — | Options `clock` and `image` (from M4), translated as "Clock" / "Image". State `None` → unknown (F7.4) |
| `image_player` | media_player | — | PLAY_MEDIA, PLAY, STOP, BROWSE_MEDIA |
| `clock_style` | select | config | Options `planet_yellow`, `planet_gradient`, `planet_blue`, `frame_gradient`, `frame_yellow`, `frame_multicolor`, `hourglass_yellow`, `hourglass_orange` for the values 1–8, from the drawing of the time screen on a 32×32 (V5). Translated as "Planet, yellow" … "Hourglass, orange". The Store keeps the value as an integer. |
| `clock_24h` | switch | config | Name "Clock 24-hour format" |
| `clock_show_date` | switch | config | |
| `image_fit` | select | config | `fill` → crop, `fit` → fit |
| `orientation` | select | config | Options `normal`, `rotated_counterclockwise`, `upside_down`, `rotated_clockwise` for the values 0–3 (V8), translated as "Normal", "Rotated 90° counterclockwise", "Upside down", "Rotated 90° clockwise". The Store keeps the value as an integer. |
| `auto_reconnect` | switch | config | |
| `sync_time` | button | config | |
| `disconnect` | button | config | |
| `connected` | binary_sensor | diagnostic | device_class `connectivity` |
| `width`, `height` | sensor | diagnostic | Unit `px`, values from `entry.data` |
| `signal_strength` | sensor | diagnostic | device_class `signal_strength`, dBm, `state_class` measurement, disabled by default. While connected it shows the last known value (§4.2) |

Platforms declare `PARALLEL_UPDATES = 0`, because the controller already serializes the commands.

---

## 7. Setup (config flow)

- **`async_step_bluetooth`**: sets `unique_id = address` and aborts the flow if the panel is already configured. Then it goes to **`bluetooth_confirm`**, a form with the `name` field (the Bluetooth name by default).
- **`async_step_user`**: lists the entries of `async_discovered_service_info` that match the name `LED_BLE_*` or the service `0000fa01-…`, excluding those already configured. The list has an extra "Enter address manually" entry, which leads to **`manual`** (address and name). If there's no panel, the flow goes straight to `manual`.
- **Check** (common to all paths): a temporary `IPixelConnection` connects and asks for the panel info. The command is the same as `set_time`, built with HA's time. Then it disconnects. On error the form is shown again with `cannot_connect`.
- **Entry created**:
  - title equal to the name, which becomes the device name and therefore the entity_id prefix;
  - `data = {address, device_type, width, height}`;
  - no `options`: the settings are entities.
- **Manifest**:
  - `bluetooth` matchers on `local_name: LED_BLE_*` and `service_uuid: 0000fa01-…`, both `connectable: true`. The test panel transmits only its name and manufacturer data, with no UUID, and its GATT service is `000000fa-…`: only the first matcher recognizes it;
  - `dependencies: ["bluetooth_adapters", "media_source"]`;
  - `integration_type: device`, `iot_class: local_push`, `requirements: ["pypixelcolor==0.5.0"]`.

---

## 8. Images

`image_source.async_resolve(hass, media_id)` returns `ImageData(bytes, format, title)`. The possible cases:

- `media-source://…`: `async_resolve_media`. If `PlayMedia.path` is present, the file is read from disk: that's the case of My media files, which work even when the signed URL has expired. Otherwise `url` is downloaded. The title is the file name.
- `/local/…`: read directly from `config/www/…`, without HTTP, so it also works during startup. The resolved path must stay inside `www`: `..` and `%2e%2e` give `image_unavailable`. Only a relative path starting with `/local/` is a local file: an absolute URL with a `/local/` path is downloaded.
- `http(s)://…`: downloaded with HA's aiohttp session, with a 30 s timeout. The download stops before starting if the `Content-Length` exceeds 10 MB, otherwise as soon as the bytes received exceed it (F8.8). Redirects are followed.
- **10 MB limit**: it applies to the source file, read from disk or downloaded. What reaches the panel is much smaller, because it's reduced to the panel's resolution.
- **Format**: recognized from the bytes with Pillow, in the executor, reading only the header. GIF, PNG, JPEG, WebP and BMP are allowed, whatever the file name extension.
- **Conversion** (`protocol.image`, in the executor because it's heavy work):
  - a still image becomes a PNG with Pillow before reaching pypixelcolor. It's rotated as its EXIF says, as phone photos need, and modes such as CMYK or P become RGBA. pypixelcolor's conversion ignores the EXIF and doesn't handle CMYK;
  - a GIF passes as it is: pypixelcolor re-encodes it frame by frame, with its timings and loop;
  - `protocol.image` repeats the steps of `send_image_hex` with its internal functions `_resize_image` and `_build_send_plan`, with `resize_method` taken from `image_fit` and transparent areas turned black. Between the two steps it pads the GIF's global color table to 256 colors (V10): Pillow sizes each table to the colors of its frame, and the panel freezes on a frame whose local table is larger than the global one. The added entries are black and unused, and the frames don't change.
- **Transfer**: 12 KB windows, with an ACK after each window (`05 00 03 00 01` for a GIF, `05 00 02 00 …` for a PNG) and `… 03` at the end. After the last window only the `03` arrives. Only ACKs that echo bytes 2–3 of the window are accepted (§13). Durations measured on 2026-11-08 through the USB adapter: 4.6–5.1 s per window, so 22–24 s for a 59 KB GIF, and 0.2–1.3 s for a small image. They weren't measured through the proxy, because that day it wasn't registered in HA.
- **Later playback**: the state saves the original `media_id`, never the signed URL (F8.7).
- **Media browser**: `media_source.async_browse_media` with a filter on the MIME types `image/gif`, `image/png`, `image/jpeg`, `image/webp`, `image/bmp` and `image/x-ms-bmp` (the name some Python versions give to BMP). Folders stay visible.

---

## 9. Diagnostics (F10.4)

`async_get_config_entry_diagnostics` returns:
- `entry.data`;
- the complete desired state;
- the connection state: connected, reachable, last connection and last disconnection, last error, adapter or proxy of the last connection;
- the `Signal strength` RSSI, even if the sensor is disabled;
- the last `BluetoothServiceInfo`: RSSI, source (adapter or proxy), connectable;
- the text of `async_address_reachability_diagnostics(…, CONNECTION)`.

The query string of image URLs, which can contain tokens, is redacted with `image_source.redact_url`.

**Adapter or proxy of the connection**: while connected the last advertisement doesn't say (V4), and HA chooses the path by itself among the scanners that hear the panel. HA has no public API to ask, so `IPixelConnection.adapter` reads the private attribute `_connected_scanner` of `HaBleakClientWrapper`. If the attribute disappeared the value would become `None`, without errors, and `test_connection.py` would flag it when HA is updated. The controller copies it on every connection, so it stays readable after a disconnection.

---

## 10. Errors

All actions raise translated exceptions, with `translation_domain = DOMAIN` (T2):

| Key | Type | When |
|---|---|---|
| `not_reachable` | `HomeAssistantError` | The connection isn't possible |
| `command_failed` | `HomeAssistantError` | Failed write or missing ACK |
| `no_image` | `ServiceValidationError` | `Mode = Image` or Play without an image |
| `image_too_large` | `ServiceValidationError` | File over 10 MB |
| `image_unsupported` | `ServiceValidationError` | Format not allowed |
| `image_unavailable` | `HomeAssistantError` | Failed download or read |

The messages about images name the source without the query string, which can contain a token. The same goes for the error text: aiohttp's repeats the full URL, so an HTTP error becomes just `<status> <message>`, for example `429 Too Many Requests`.

Logs use `debug` for traffic and `warning` for unexpected disconnections and failed restores. The `info` level isn't used for every command, as the reference does.

---

## 11. Quality and tools

- **Environment**: `uv` with Python 3.14. `pyproject.toml` contains only development tools, because the integration isn't a package: `pytest-homeassistant-custom-component==0.13.371`, `pypixelcolor==0.5.0`, `ruff`. Pytest is configured with `asyncio_mode = auto`.
- **Lint and formatting**: `ruff check` and `ruff format`.
- **Tests** (`tests/` folder):

| File | What it checks |
|---|---|
| `test_protocol.py` | The bytes of every command. The clock date passed as `DD/MM/YY` (pypixelcolor accepts only a two-digit year, and the weekday stays right because 2000 years are whole Gregorian cycles). Decoding of the panel info. Images: GIF frames and timings, 256-color global table (V10), windows, still images as PNG, Fill and Fit, transparency, EXIF, CMYK, corrupt images. ACKs filtered by command. |
| `test_image_source.py` | URLs (title, errors, limit from the `Content-Length` and during the download, query hidden in the error text too), `/local/` (formats, paths outside `www`, limit), media source (file from disk, URL), formats not allowed |
| `test_connection.py` | With a fake `BleakClient`: 244-byte chunks, waiting for the ACKs, timeout → error, captured response, lock order, unexpected disconnection |
| `test_controller.py` | Power rules. Immediate send conditioned on `Mode` (D10). Restore order, and a failed restore repeated before the next command. Reconnection at the first advertisement (`sleep(0)`). Pause after a failed attempt. `Disconnect` turning off `Auto reconnect`. On-demand connection. Availability with V4. Falling back to the clock. HA time in Europe/Rome with the system in UTC. Scheduled syncs: midnight, daylight saving, screen off, no reconnection. |
| `test_state.py` | Defaults, complete (de)serialization, missing or invalid values falling back to the default |
| `test_config_flow.py` | Discovery and name confirmation, filtered list, manual entry, `cannot_connect`, `already_configured` |
| `test_init.py` | Startup with no panel present (entry loaded, entities unavailable), entry unload |
| `test_entities.py` | entity_ids with the prefix, categories, availability, action calls |
| `test_media_player.py` | URL, `/local/` and media source sources. Fit and Fill. Visible errors (size, format, unreachable source). The buffering → playing sequence, Stop → Clock, Play. Filtered Media browser, over WebSocket. The image restore, the fallback to the clock, F8.10 and the HA restart are in `test_controller.py`. |
| `test_diagnostics.py` | Snapshot with syrupy, included in pytest-homeassistant-custom-component |

- **CI** (GitHub Actions): `hassfest`, HACS validation (`hacs/action`), `ruff`, `pytest`.
- **Deploy to the maintainer's HA**: `scripts/deploy.sh`, taken from the reference. It rsyncs to HA's container and restarts it, with the host and config folder taken from local, unversioned settings. It has the `--dry-run`, `--logs` and `--no-restart` options, and `custom_components/ipixel_color_se` as the destination folder.
- **Checks on HA during development**, all verified on 2026-11-07:
  - Claude deploys and restarts the container on its own, with the maintainer's permission;
  - logs and registries are read over SSH;
  - entity states, actions and config flows go through the REST API, with a token kept outside the repository;
  - the maintainer does the visual checks on the panel and the power cuts.

### Release

- **HACS downloads the tag as it is**, with no zip attached: it's about twenty small files, and a zip would need one more workflow to maintain.
- **The version** in `manifest.json` matches the tag (`0.1.0` and `v0.1.0`).
- **Clean install on the maintainer's HA**: the config entry is removed and added again, to try a new user's path. The device stays without an area until all the entities exist.

### Repository layout

```
ha-ipixel-color-se/
├── custom_components/ipixel_color_se/
│   ├── __init__.py  manifest.json  const.py  config_flow.py
│   ├── protocol.py  connection.py  state.py  controller.py  image_source.py
│   ├── entity.py  switch.py  number.py  select.py  button.py
│   ├── media_player.py  binary_sensor.py  sensor.py  diagnostics.py
│   ├── icons.json  translations/en.json  brand/
├── tests/
├── scripts/deploy.sh
├── specs/
├── .github/workflows/
├── pyproject.toml  hacs.json  README.md  LICENSE (GPL-3.0)  CLAUDE.md
```

**What is taken from the reference**:
- the Bluetooth matchers;
- the use of `establish_connection`;
- the ACK decoding and the windowed transfer;
- the reconnection from advertisements (pause and `sleep(0)`);
- the download with a size limit and the player's Media browser;
- the power rules checked on the panel.

**What isn't taken**: `common.py`, reading the state from other entities, the text rendering, the fonts, the lights used as color pickers.

---

## 12. Work plan

Every milestone ends with green tests, a deploy to the maintainer's HA and a real test.

**During development the old integration must be disabled**: the panel accepts a single connection (T5).

| # | Milestone | Content | Panel checks | Done when |
|---|---|---|---|---|
| **M0** | Foundations | `git init`, layout, `pyproject`, ruff, CI, manifest, `CLAUDE.md` (with the panel knowledge taken from the reference), `deploy.sh`. The empty integration loads. | — | CI is green and HA lists the integration among those that can be added |
| **M1** | Connection and setup | `protocol` (panel info), `IPixelConnection`, complete config flow, device, `Connected`, `Width`, `Height`, basic diagnostics | **V9**: do all the commands used get an ACK? **V4**: does the panel keep advertising while connected? | The panel is discovered, configured with a name and connected. The entity_ids have the prefix. |
| **M2** | Controller and basic commands | `state`, `controller`, Store, `Power`, `Brightness`, `Orientation` (raw options), `Auto reconnect`, `Disconnect`, reconnection, availability, restore steps 1–4 | **V1**, **V2**, **V6**, **V8**. The orientation options are renamed and the brightness minimum is set. | I unplug and replug the panel: it reconnects by itself and turns the screen off again if it was off. `Disconnect` frees the panel for the app. |
| **M3** | Clock | `Mode` (`Clock`), clock options, `Sync time`, scheduled syncs, clock restore | **V3**, **V5**, **V7**. The styles get their names. | Correct time with HA's time zone. The style changes at once. After a power cut the clock comes back. |
| **M4** | Images | `image_source`, `Image player`, `Mode` `Image`, `Image fit`, image restore with the fallback to the clock | **V10**, **V11**, **V12**, transfer durations. The GIF color table is fixed. | GIF and JPG from the Media browser, `/local/` and URL. `Fit` and `Fill` correct. The image comes back after a power cut. |
| **M5** | Polish and release | `Signal strength`, complete diagnostics, icons, `brand/`, README, HACS validation, `v0.1.0` tag on GitHub, final clean install on the maintainer's HA and removal of the old integration | — | The spec is met (§5 F1–F11). The old integration is removed. |

### Milestone outcomes

The outcomes of the panel checks are in [panel-checks.md](../panel-checks.md).

| Milestone | Date | Outcome |
|---|---|---|
| **M4** | 2026-11-08 | Through the USB adapter. GIF from the Media browser: buffering → playing, with the right timings after V10. The Media browser shows only images. JPG from the Media browser and from a URL (Picsum, with a redirect to a URL with `?hmac=…`): Fit with black bars above and below, Fill cropped, and every `Image fit` change downloads and resends the image. Transparent PNG from `/local/`: black background. Stop → clock with `Mode = Clock`, Play and `Mode = Image` resend the photo. Visible errors: a 12.6 MB file, a TIFF, a nonexistent host. A Wikimedia URL answered `429 Too Many Requests` to HA's session, and the error showed that aiohttp's text repeated the full URL (§10). Brightness halfway through a transfer: sent 3 ms after the final ACK. GIF chosen with the screen off: `Power` back on. Power cuts: the image comes back, a screen that was off stays off and turning it on resends the image, and a deleted source brings back the clock with `Mode = Clock`. HA restart: the My media image is read again from disk after startup. ACKs and durations in §8. |
| **M5** | 2026-11-08 | `Signal strength`: the RSSI swings by 5–6 dBm between advertisements, and the initial rule (3 dBm or 30 s) wrote about twice a second. With the limit of one write every 30 s (§4.2): one write in 200 s with the panel disconnected. Diagnostics downloaded from the UI: adapter, RSSI and complete state, no token. Icon visible on the integrations page and on the device page, served from `brand/`. Installation from HACS as a custom repository (`v0.1.0`): the 22 files are identical to the tag, the recreated config entry has the same entity_ids and the device has no area. HA restores the `disabled_by` of a deleted entity when the same `unique_id` comes back: `Signal strength`, enabled for the tests, came back enabled and was disabled by hand. The default is checked by the tests. Regression with GIFs sent by URL from an external tool, through the ESPHome proxy, which was back online with a better signal than the USB adapter. Power cut: the GIF comes back. HA restart with a temporary URL that had expired (404): clock with `Mode = Clock` (F9.4). Old integration removed: no orphan entity or device, and no error in the log after the restart. `Power`, the clock and the GIF from the Media browser weren't checked visually again on this installation: their code hasn't changed since M4. |

---

## 13. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| A simple command gets no ACK (V9) | Spurious errors | Checked in M1: they all get one, except `set_time`, which gets a response and is treated as a request. |
| pypixelcolor changes its internal modules | Breakage on update | Exact pin and imports confined to `protocol.py`, covered by `test_protocol.py` |
| The panel doesn't advertise while connected (V4) | `Signal strength` frozen during the connection | Confirmed in M1. While connected the sensor shows the last known value (§4.2). Accepted and documented in the README (the sensor is disabled by default) |
| `_connected_scanner` is a private attribute of habluetooth | An HA update may remove it | The diagnostics show `adapter: null`, without errors. `test_connection.py` fails when HA's pin is updated. |
| Restore on every HA start | A GIF is retransmitted on every restart: up to about 25 s for a 60 KB GIF through the USB adapter | Accepted: it guarantees consistency (F9). During startup the image follows in the background (§4.3) and meanwhile the player is buffering. |
| External URLs no longer reachable at restore | The image doesn't come back | Fallback to the clock (F9.4), checked in M4 with a deleted file |
| Sites that refuse HA's session (Wikimedia answers 429 to its User-Agent) | A URL that works in the browser fails in HA | The error is visible with the HTTP status. Accepted: the User-Agent is HA's. |
| Duplicate or late ACKs (seen in M2 with dropped clients that weren't closed, now fixed) | In windowed transfers an extra ACK could let the next window go too early | Fixed in M4: only ACKs that echo bytes 2–3 of the window are accepted (V9) |
| GIFs the panel doesn't animate (V10) | The GIF stays frozen on its first frame | Fixed in M4: the global table is padded to 256 colors. A pypixelcolor update must be rechecked with a GIF of few colors. |
| ESPHome proxy with unstable WiFi (seen in M2) | Slow ACKs, writes timing out after 30 s, the connection dropping. For images: a 12 KB window takes about 5 s through the USB adapter, and through the proxy it can exceed the 8 s ACK wait | The error appears in the interface (`command_failed`). The dropped connection is followed by the reconnection with the restore, which realigns the panel with HA's state. If transfers through the proxy time out, the wait is lengthened for the windows only. |
| Panel and HA competing with the phone app | Stolen connections | `Disconnect` turns off `Auto reconnect` (F3.6) |
