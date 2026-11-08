# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration (HACS) for iPixel Color Bluetooth LED matrix displays (sold as the "B.K. Light LED Pixel Board"). Domain: `ipixel_color_se`. All code is in `custom_components/ipixel_color_se/`. Minimum Home Assistant version: 2026.10.0 (Python 3.14), with no compatibility code for older versions.

It's a rewrite of the reference integration `ha-ipixel-color` (upstream `cagcoach/ha-ipixel-color`, local checkout `../ha-ipixel-color`, branch `import-server-version`). Read the reference for behavior proven on the panel, but never modify it.

The design documents in `specs/` are written in Italian and are the source of truth:

- `specifica-funzionale.md`: **what** to build. Requirements F1–F11 and T1–T9, the entity model, and the panel checks V1–V9.
- `piano-tecnico.md`: **how** to build it. Architecture, modules, flows, tests and milestones M0–M5 (§12).

Work one milestone at a time. Start a milestone only when the user asks, and don't implement anything that belongs to a later one. When a decision changes, update the spec or the plan.

**Current state**: M5 done, so phase 1 is complete: `v0.1.0` is released and the user's HA runs it from HACS. M5 added `Signal strength`, the complete diagnostics, the icons, `brand/`, the README and the HACS validation. Before that: M4's images (`image_source.py`, the `Image player`, `Mode` with `clock` and `image`, `Image fit`, the restore with the fallback to the clock, F9.4); M3's clock, its options, `Sync time` and the scheduled syncs; M2's `Power`, `Brightness`, `Orientation`, `Auto reconnect`, `Disconnect`, the Store and the reconnection; and M1's `Connected`, `Width` and `Height`. Text is phase 2 and isn't started. Update this line at the end of each milestone.

## Conventions

- **Language**: code, identifiers, comments, logs, entity names, entity_ids and UI strings are in English. Talk to the user in Italian; the specs stay in Italian.
- **Strings**: `translations/en.json` is the only strings file. There is no `strings.json`, because the two diverged in the reference. Icons go in `icons.json`. Hassfest requires `config.step` in `en.json` as soon as there's a config flow, even if it's empty. HA drops the trailing period of translated exception messages, so write them without one.
- **Entities**: `_attr_has_entity_name = True`, `translation_key = key`, `unique_id = f"{address}_{key}"`, with the keys from plan §6. Since HA 2026.10, identifiers and connections are unique only within a config entry, so our device never merges with the old integration's: look devices up with `async_get_device_by_identifier(identifier, entry_id)`, not the deprecated `async_get_device`. Don't set a suggested area. If the device already has an area when its entities are created, HA puts the area in the entity_ids too (that's how the reference got `binary_sensor.taverna_pixel_led_display_connected`). Check the real entity_id in HA after adding an entity rather than deriving it from the name.
- **Errors**: actions raise translated exceptions (`HomeAssistantError` or `ServiceValidationError` with `translation_domain=DOMAIN`), with the keys from plan §10. A failed action must show in the UI and fail the automation, not only end up in the log.
- **Logging**: `debug` for traffic, `warning` for unexpected disconnects and failed restores. Don't log every command at `info`.
- **No polling** (T4): states change on events. Fixed data (address, type, width, height) is read once by the config flow and kept in `entry.data`.
- **pypixelcolor** is pinned exactly (`pypixelcolor==0.5.0`) in both `manifest.json` and `pyproject.toml`: keep the two in sync. Only `protocol.py` may import it, because we use its internal modules.
- Bleak, bleak-retry-connector and habluetooth ship with HA. Don't list them in the manifest's `requirements`.
- Platforms set `PARALLEL_UPDATES = 0`: the controller already serializes commands.
- **Commits**: Conventional Commits (the `git-commit-conventions` skill). Ask the user before committing or pushing.
- **Nothing about the user's setup in the repository**: no host names, IP addresses, paths, token locations, or identifiers of the user's panel and adapters, in code, tests, docs or commit messages. They live in `CLAUDE.local.md` and `scripts/deploy.env`, both untracked. Tests use made-up addresses.

## Development workflow

```bash
uv sync                   # .venv with HA 2026.10.0 and the dev tools
uv run ruff check         # lint
uv run ruff format        # format (CI runs it with --check)
uv run pytest             # tests
docker run --rm --platform linux/amd64 -v "$PWD":/github/workspace ghcr.io/home-assistant/hassfest
```

- `pyproject.toml` only holds development tools: the integration isn't a Python package, and HA installs its requirements from `manifest.json`.
- `pytest-homeassistant-custom-component==0.13.371` pins `homeassistant==2026.10.0`, the minimum supported version. It doesn't install the requirements of HA's own integrations. We depend on `bluetooth_adapters`, which pulls in `bluetooth` and `usb`, so `aiousbwatcher`, `dbus-fast` and `serialx` are listed explicitly, with the versions from the HA manifests. Update them when you bump the pin.
- `tests/conftest.py` enables custom integrations and mocks the Bluetooth stack (`enable_bluetooth`) in every test. Pytest runs with `asyncio_mode = auto`.
- The `mock_panel` fixture (`tests/common.py`) puts a simulated panel in range: it patches `establish_connection`, `async_ble_device_from_address`, `async_address_present`, `async_register_advertisement_callback`, `async_track_unavailable` and `async_discovered_service_info` where our modules import them. It answers like the real panel (info frame to `set_time`, ACK to the rest, sent before the write returns) and tracks `screen_on` (brightness, orientation, the clock and `set_time` turn it on, checks V1 and V7). `commands` names what was written (`["set_time", "orientation 0", "power on"]`, `"clock 3 12h date"`, `"gif"`, `"gif, continued"`, `"png"`); `panel_time` and `panel_date` decode the time and date a command carries. `chunks` holds the raw writes and `writes` the frames reassembled from them by their length prefix. Image windows get an ACK `1` each and `3` at the end, like the real panel. The finished transfer is in `image`, decoded by `shown` as a Pillow image, and it turns the screen on. Change its `responder`, `info_frame`, `present` or `*_error` attributes to simulate failures.
- Test images come from Pillow, never from files: `gif()`, `noise_gif()` (doesn't compress, so it fills several windows) and `still()` in `tests/common.py`. The `config_dir` fixture gives HA a temporary config dir with `www` and a `media` folder as "My media".
- `aioclient_mock` responses have no `content_length` (use the `Content-Length` header), and their `raise_for_status` builds an error with a fake URL. To test the text of a real aiohttp error, pass it with `exc=`.
- `present` stands for HA's Bluetooth history. `advertise()` calls the advertisement callbacks *before* setting `present`, as HA does, so a test fails without the `sleep(0)`. `vanish()` fires the unavailable callbacks, `lose_power()` drops the connection and makes connecting fail, `power_on()` boots the screen on and advertises.
- `Store.async_delay_save` compares the real loop time with its next write time: after several saves in a row, `async_fire_time_changed` only reschedules the write. Test the delayed save with a single change, and several changes through a reload (unloading saves at once).
- The first connection runs as a background task: wait for it with `hass.async_block_till_done(wait_background_tasks=True)`. Freeze time with `@pytest.mark.freeze_time`, not `freezer.move_to` in the test body, when the test also uses `hass_client`: a token issued "in the future" gets a 401.
- Scheduled syncs are tested with `freezer.move_to` and `async_fire_time_changed`. With frozen time an asyncio timeout never expires, so simulate a failed command with `write_error`, not a missing ACK, or the test hangs. `uv run pytest --timeout 30` catches a hang.
- `tests/snapshots/` holds the syrupy snapshots. After a deliberate change, regenerate them with `uv run pytest --snapshot-update` and review the diff.
- Ruff excludes `specs/`, because it would reformat the code blocks in the Markdown documents.
- The hassfest image is amd64 only: on Apple Silicon it runs emulated.
- CI (`.github/workflows/ci.yml`) runs ruff and pytest, hassfest, and the HACS validation, with no check ignored. The HACS check `brands` looks for `custom_components/ipixel_color_se/brand/icon.png` in the repository tree. HACS also checks the GitHub repository's description and topics.
- `brand/` holds `icon.png` (256×256) and `icon@2x.png` (512×512). HA serves them at `/api/brands/integration/<domain>/<image>`, and the missing variants (logo, dark) fall back to `icon.png`.
- The `adapter` in the diagnostics comes from habluetooth's private `_connected_scanner`. `test_ha_client_wrapper_still_tracks_the_scanner` fails if it goes away.
- Releases: HACS downloads the tag as it is, with no zip asset. Keep `version` in `manifest.json` equal to the tag.

### Deploying to the user's Home Assistant

Changes are tested on the user's production HA, a Docker container on an SSH host. No release is needed. The host, the config dir, the API address and where the token is are in `CLAUDE.local.md`; `scripts/deploy.sh` reads them from `scripts/deploy.env` (copy `scripts/deploy.env.example`).

```bash
scripts/deploy.sh --dry-run   # show what would change on the host
scripts/deploy.sh             # rsync the integration, then `docker restart homeassistant`
scripts/deploy.sh --logs      # same, then follow the HA log filtered on "ipixel_color_se"
scripts/deploy.sh --no-restart
```

- You may deploy and restart the container without asking.
- The script **mirrors** `custom_components/ipixel_color_se/` onto the host: anything there that isn't in the repo (except `__pycache__`) gets deleted. `HA_SSH_HOST` and `HA_CONFIG_DIR` are required; `HA_CONTAINER` defaults to `homeassistant`. Variables set in the environment win over `scripts/deploy.env`.
- Python changes need a full HA restart: reloading the config entry doesn't re-import modules.
- The user's HA runs the release installed from HACS. `scripts/deploy.sh` overwrites that copy while HACS keeps reporting the version it downloaded: after testing a build this way, download the release again from HACS.
- Recreating a config entry doesn't reset the registry: when the same `unique_id` comes back, HA restores the entity's old `disabled_by` and the device's id. A sensor enabled by hand stays enabled, so check a default in the tests, not by recreating the entry.
- Logs: `home-assistant.log` in the config dir (`/config` in the container), or `docker logs <container>`, over SSH.
- REST API: `http://<ha-host>:8123/api/`, with an admin token kept in a file outside the repository. **Never print it**: send it as `-H "Authorization: Bearer $(tr -d '[:space:]' < "$TOKEN_FILE")"`. Entity states, actions and config flows can all be checked this way (for example `GET /api/config/config_entries/flow_handlers`).
- The user does the visual checks on the panel and the power cycles.
- Debug logging without a restart: call `logger.set_level` with `{"custom_components.ipixel_color_se": "debug"}` through the REST API. It lasts until the next restart.
- **Panel checks without the integration** (how V3, V4, V5, V7 and V9 were done): with no integration connected to the panel, pipe a bleak script into the container, `ssh <host> 'docker exec -i <container> python3 -' < probe.py`. It talks to BlueZ directly through the host's local adapter. Log every notification with a timestamp, and leave the panel as you found it. For advertising, HA's bluetooth config entry diagnostics (`GET /api/diagnostics/config_entry/<id>`) give the `time` of the last advertisement per address.

- The probe needs the local adapter to hear the panel. When only the ESPHome proxy does, go through the integration instead (for V6, a temporary build lowered the minimum of `Brightness` to 0).

Debug logging, in HA's `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.ipixel_color_se: debug
```

## Planned architecture

Plan §2 has the details. The layers:

```
entities (switch, number, select, media_player, button, binary_sensor, sensor)
        │  call methods on the controller and listen to it
        ▼
IPixelController ── desired state (DisplayState) ── Store (.storage)
        │  rules, reconnection, restore, time sync
        ├── image_source      resolves, downloads and validates images
        ▼
protocol              builds commands (SendPlan) with pypixelcolor
        ▼
IPixelConnection      HA Bluetooth + bleak-retry-connector, ACKs, replies, lock
```

| Module | Role |
|---|---|
| `protocol.py` | The only module that imports pypixelcolor. Pure functions that return a `SendPlan` (power, brightness, orientation, clock mode, set time, image), plus decoding of the panel info. No HA. |
| `connection.py` | `IPixelConnection`: connect and disconnect, send a `SendPlan` and wait for the ACKs, request and reply, connection change callbacks |
| `state.py` | `DisplayState`, `ClockSettings`, `Mode`, `ImageFit`, serialization and defaults. No HA. |
| `controller.py` | `IPixelController`: owns the connection, the state and the Store. Exposes the actions, applies the state rules, handles reconnection, reachability, restore and time sync, and notifies the entities |
| `image_source.py` | Turns a `media_id` (URL, `/local/…`, `media-source://…`) into bytes, format and title, with the 10 MB limit and format validation |
| `entity.py` | `IPixelEntity` base class: naming, `unique_id`, `device_info`, availability, controller listener |

- **A controller, not a `DataUpdateCoordinator`**: there's nothing to poll. The controller holds the desired state, the rules and the command sequences. Entities register with `controller.async_add_listener(callback)` and are thin views with no logic.
- **One source of truth**: the desired state lives in the controller and is saved in a single `Store` per display (`ipixel_color_se.<entry_id>`). Entities never read each other's state, unlike the reference. `None` values (brightness, mode) mean "never set": the integration doesn't change the panel until the user asks.
- **Restore** on every successful connection, including the first after an HA start: time, orientation, brightness if set, then screen off if `power` is false, otherwise the last content (plan §4.3).

## What we know about the panel

Learned on the real panel with the reference integration.

### One connection only

The panel accepts a single BLE connection. While HA holds it, the phone app and any other HA instance can't connect. The `Disconnect` button frees it, and turns off `Auto reconnect` so HA doesn't take it straight back.

### GATT and framing

- Advertising: local name `LED_BLE_*` and manufacturer data for company 21076 (`0x5254`), but **no service UUID**. The manifest's second matcher, `service_uuid: 0000fa01-…` (kept from the reference), never matches this panel: only the name does.
- GATT: service `000000fa-0000-1000-8000-00805f9b34fb`, with write characteristic `0000fa02-…` (write and write without response) and notify characteristic `0000fa03-…`. The panel also has a `0000ae00-…` service (`ae01` write, `ae02` notify) that nobody uses.
- Commands are framed as `[length LE16][opcode LE16][payload]`, where the length includes the 4 header bytes. Brightness, for example, is opcode `0x8004` with a 1–100 byte, and power is `05 00 07 01 <0|1>`.
- The clock is `0b 00 06 01 <style> <24h> <date> <yy> <mm> <dd> <isoweekday>`, and `set_time` is `08 00 01 80 <hh> <mm> <ss> 00`. pypixelcolor's clock command only takes a two-digit year (`DD/MM/YY`). The weekday stays right because 2000 years are whole Gregorian cycles.

### Transfers and ACKs

- Each window of a transfer is written in 244-byte chunks. On the local BlueZ adapter a single write can't exceed 512 bytes.
- After each window the panel answers `05 00 xx xx <status>`: status `0` or `1` means the window was received, `3` means the transfer is done. Wait up to 8 s for it before sending the next window.
- Check V9 (2026-11-07): every simple command (brightness, orientation, power on and off, clock mode) gets an ACK `05 00 <id> <type> 01`, echoing bytes 2–3 of the command, in about 30 ms. The ACK can arrive **before the write itself returns**, so the wait must be armed before writing.
- **`set_time` gets no ACK**: the panel answers with its info frame `0c 00 01 80 <type> …`, because it's the same command as pypixelcolor's `get_device_info`. pypixelcolor's own `set_time` plan waits for an ACK and would always time out after 8 s: in `protocol.py` it's a request with a response instead. Byte 4 is the panel type: `0x81` means 32×32. Bytes 5 and 6 are the minute and second just set, and byte 8 is the month, which only a clock command sets (check V3).
- Image windows (2026-11-08): `[len LE16][03 00 gif | 02 00 png][option: 0 first, 2 continued][total size LE32][CRC LE32][02 gif | 00 png][slot]`, then up to 12 KB of the file. Each window gets `05 00 03 00 01` (GIF) or `05 00 02 00 01` (PNG). After the last one only `… 03` arrives. We accept only ACKs that echo bytes 2–3 of the window.
- Transfer times through the local USB adapter: 4.6–5.1 s per 12 KB window, so a 59 KB GIF takes 22–24 s and a small image 0.2–1.3 s. The 8 s wait per window has little margin. They haven't been measured through the ESPHome proxy.

### Images

- pypixelcolor's `send_image_hex` resizes a GIF frame by frame and saves it with Pillow. Pillow sizes each color table to the colors of its frame: the first frame gets the global table, and later frames get local ones.
- Check V10 (2026-11-08): the panel **freezes on the first frame whose local color table is larger than the global one**, and keeps showing the frame before it. A 4-frame GIF with a 64-color global table and 128-color local tables never moved. Equal tables (4/4, 256/256) and smaller local ones (256/4) play. `protocol.image` runs `send_image_hex`'s steps itself (`_resize_image`, then `_build_send_plan`) and pads the global table to 256 colors in between. Recheck with a GIF of few colors whenever pypixelcolor is bumped.
- Frame delays of 80 ms to 3 s play correctly.
- A still image becomes a PNG with Pillow first (EXIF rotation, CMYK and palette modes to RGBA). pypixelcolor's own conversion ignores the EXIF orientation.
- Check V11 (2026-11-08): turning the screen off and on by command keeps the GIF. `power on`, or brightness with the screen off, shows it again, and it keeps running while the screen is off. After a power cycle the panel shows its built-in GIFs, so turning the screen on resends the image only when it wasn't sent on the current connection.
- Check V12 (2026-11-08): `set_time` with an image on screen leaves the image as it is. Scheduled syncs and `Sync time` send only `set_time` when the mode is `image`.
- A new image replaces the shown one directly: the one the panel had in memory doesn't flash back during the transfer.
- Some sites refuse HA's HTTP session. Wikimedia answered `429 Too Many Requests` to HA's User-Agent, while curl with the same User-Agent got the image. Picsum (`https://picsum.photos/id/<n>/<w>/<h>.jpg`) works, through a redirect to a URL with `?hmac=…`. aiohttp's error text repeats the whole URL, query and all, so `image_source` reports only the status and message.

### Power state

- The panel can't be asked whether the screen is on, nor its brightness: the device-info reply carries neither. HA can only show the last state it sent.
- Any content sent to the panel (an image, a GIF, the clock) turns the screen back on.
- Check V1 (2026-11-07): brightness and orientation turn the screen back on too, so they set `power` to on. In the restore the screen-off command goes last. With the clock as content, waking the screen this way also sends `set_time` and the clock, because the panel shows the clock it had, maybe stale.
- Check V7 (2026-11-07): `set_time` turns the screen back on too, showing the clock. It doesn't flicker or bring the GIFs back: it restarts the clock's cycle at the date screen. So the scheduled syncs skip a screen that's off, turning the screen on sends `set_time` and the clock, and `Sync time` sets `power` to on.
- Check V2 (2026-11-07): the panel keeps its brightness through a power cycle. Restoring it still covers changes made elsewhere, such as in the phone app.
- Check V6 (2026-11-07): brightness 0 doesn't turn the screen off. It leaves a faint light that looks the same as 1, so `Brightness` starts at 1.
- Check V8 (2026-11-07): orientation 0 is normal, 1 turns the content 90° counterclockwise (the top goes to the left), 2 turns it upside down, 3 turns it 90° clockwise. The visible content turns at once. The options are `normal`, `rotated_counterclockwise`, `upside_down` and `rotated_clockwise`; the Store keeps the number.
- An HA restart leaves the screen as it was, because the panel keeps its power.
- A power cycle boots the panel with the screen on, showing its built-in GIFs: the mode isn't restored.
- Check V3 (2026-11-07): the panel loses its time and date without power, and boots at about 08:00:00. The restore's `set_time` and clock put both back. With power, it advances the date and weekday by itself at midnight.

### Clock

- Check V5 (2026-11-07), on the 32×32 panel: the clock styles are the values 1 to 9. 0 gets an ACK with status 1 but shows nothing (the panel keeps the previous content), and 10 gets status 0. pypixelcolor accepts 0 to 8, so we offer 1 to 8, default 1. The ninth (an hourglass with white sand) waits for a pypixelcolor PR.
- Every style alternates a date screen (weekday in pink over month.day in light blue, about 5 s) with a time screen (about 10 s). The time screen names the options: 1–3 a planet with a ring, the hour above and minute.second below, in yellow, gradient or blue; 4–6 a dashed 1-pixel frame in gradient, yellow or one color per side; 7–8 HH:MM above an hourglass and the seconds, with yellow or orange sand. Other models may draw them differently.
- Every disconnect seen so far was the panel losing power, or the ESPHome proxy it was connected through dropping off the network.

### Advertising while connected

Check V4 (2026-11-07): the panel **stops advertising while it's connected**, and starts again, several times a second, as soon as the connection closes. So the RSSI (`Signal strength`) only updates while disconnected, and HA's Bluetooth manager eventually considers a connected panel unavailable: while connected, ignore the reachability computed from advertisements.

The RSSI swings by 5–6 dBm from one advertisement to the next, several times a second. `Signal strength` is written at most once per 30 s, with the strongest value heard in that time (plan §4.2).

### Reconnection quirks

- Use `bluetooth.async_register_advertisement_callback`: it fires on every advertisement, once per scanner that hears it. `async_register_callback` skips advertisements identical to the previous one, so it misses a panel that was unplugged and replugged within a few minutes.
- The callback doesn't replay past advertisements at startup: the first connection attempt must be made explicitly.
- The callback runs before the Bluetooth manager records the advertisement. A task started from it must `await asyncio.sleep(0)` before connecting, so the device can be looked up.
- After a failed attempt, wait 30 s before the next one.
- Serialize `connect` with a lock and return early when already connected, so a background reconnect and a command can't open two connections.
- pypixelcolor's own transport creates its own `BleakClient` from the address, bypassing HA's Bluetooth stack and its proxies. We only use pypixelcolor to build commands; the transport is ours.
- Connect with `establish_connection(..., ble_device_callback=...)`, so retries use the freshest `BLEDevice` (the proxy may have changed). Enable notifications once per connection: the reference restarted them for every command, which costs round trips through a proxy.
- When a connection drops, disconnect the dropped client too. Seen in M2 on the local adapter (bleak 3.0.2): bleak cleans up its watcher but keeps the client's D-Bus connection open, BlueZ restores that connection's `StartNotify` session on the next connection, and every frame then arrives once more for each dropped connection (twice, then three times). `client.disconnect()` on a dropped client skips the device and only closes the D-Bus connection.
- On the user's HA the panel is reached both through a local USB adapter and through an ESPHome Bluetooth proxy. Which of the two hears it changes over time.
- Through an ESPHome proxy with a weak WiFi link, ACKs take seconds and a write can time out after 30 s (`Timeout waiting for BluetoothGATTWriteResponse`): the command fails with `command_failed`, then the connection usually drops and the reconnection restores the panel. After an HA restart a proxy may also keep a stale API subscriber and stop delivering advertisements (`No scanner state received 10.0s after subscribing`) until it's power cycled.
