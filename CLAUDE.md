# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration (HACS) for iPixel Color Bluetooth LED matrix displays (sold as the "B.K. Light LED Pixel Board"). Domain: `ipixel_color_se`. All code is in `custom_components/ipixel_color_se/`. Minimum Home Assistant version: 2026.10.0 (Python 3.14), with no compatibility code for older versions.

It's a rewrite of the reference integration `ha-ipixel-color` (upstream `cagcoach/ha-ipixel-color`, local checkout `../ha-ipixel-color`, branch `import-server-version`). Read the reference for behavior proven on the panel, but never modify it.

The design documents in `specs/` are written in Italian and are the source of truth:

- `specifica-funzionale.md`: **what** to build. Requirements F1–F11 and T1–T9, the entity model, and the panel checks V1–V9.
- `piano-tecnico.md`: **how** to build it. Architecture, modules, flows, tests and milestones M0–M5 (§12).

Work one milestone at a time. Start a milestone only when the user asks, and don't implement anything that belongs to a later one. When a decision changes, update the spec or the plan.

**Current state**: M3 (clock). `Mode` with the `clock` option only, the clock options (`Clock style`, `Clock 24-hour format`, `Clock show date`) sent at once only while the clock is shown (D10), `Sync time`, the scheduled syncs at 00:00:05 and 03:05:00, and the clock in the restore (plan §4.3 step 5). Before that: M2's `Power`, `Brightness`, `Orientation`, `Auto reconnect`, `Disconnect`, the Store and the reconnection, and M1's `Connected`, `Width` and `Height`. No images, `Image player`, `Image fit` or `Signal strength` yet: they arrive in M4 and M5. Update this line at the end of each milestone.

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
- The `mock_panel` fixture (`tests/common.py`) puts a simulated panel in range: it patches `establish_connection`, `async_ble_device_from_address`, `async_address_present`, `async_register_advertisement_callback`, `async_track_unavailable` and `async_discovered_service_info` where our modules import them. It answers like the real panel (info frame to `set_time`, ACK to the rest, sent before the write returns) and tracks `screen_on` (brightness, orientation, the clock and `set_time` turn it on, checks V1 and V7). `commands` names what was written (`["set_time", "orientation 0", "power on"]`, `"clock 3 12h date"`); `panel_time` and `panel_date` decode the time and date a command carries. Change its `responder`, `info_frame`, `present` or `*_error` attributes to simulate failures.
- `present` stands for HA's Bluetooth history. `advertise()` calls the advertisement callbacks *before* setting `present`, as HA does, so a test fails without the `sleep(0)`. `vanish()` fires the unavailable callbacks, `lose_power()` drops the connection and makes connecting fail, `power_on()` boots the screen on and advertises.
- `Store.async_delay_save` compares the real loop time with its next write time: after several saves in a row, `async_fire_time_changed` only reschedules the write. Test the delayed save with a single change, and several changes through a reload (unloading saves at once).
- The first connection runs as a background task: wait for it with `hass.async_block_till_done(wait_background_tasks=True)`. Freeze time with `@pytest.mark.freeze_time`, not `freezer.move_to` in the test body, when the test also uses `hass_client`: a token issued "in the future" gets a 401.
- Scheduled syncs are tested with `freezer.move_to` and `async_fire_time_changed`. With frozen time an asyncio timeout never expires, so simulate a failed command with `write_error`, not a missing ACK, or the test hangs. `uv run pytest --timeout 30` catches a hang.
- `tests/snapshots/` holds the syrupy snapshots. After a deliberate change, regenerate them with `uv run pytest --snapshot-update` and review the diff.
- Ruff excludes `specs/`, because it would reformat the code blocks in the Markdown documents.
- The hassfest image is amd64 only: on Apple Silicon it runs emulated.
- CI (`.github/workflows/ci.yml`) runs ruff and pytest, hassfest, and the HACS validation. The HACS check `brands` is ignored until the `brand/` folder arrives in M5. HACS also checks the GitHub repository's description and topics.

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
- **Don't touch the old `ipixel_color` integration** on HA: not its folder, its config entry or its entities. The panel accepts a single connection, so from M1 on the old one must be disabled while the new one connects: ask the user.
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
