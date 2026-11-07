# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration (HACS) for iPixel Color Bluetooth LED matrix displays (sold as the "B.K. Light LED Pixel Board"). Domain: `ipixel_color_se`. All code is in `custom_components/ipixel_color_se/`. Minimum Home Assistant version: 2026.10.0 (Python 3.14), with no compatibility code for older versions.

It's a rewrite of the reference integration `ha-ipixel-color` (upstream `cagcoach/ha-ipixel-color`, local checkout `../ha-ipixel-color`, branch `import-server-version`). Read the reference for behavior proven on the panel, but never modify it.

The design documents in `specs/` are written in Italian and are the source of truth:

- `specifica-funzionale.md`: **what** to build. Requirements F1–F11 and T1–T9, the entity model, and the panel checks V1–V9.
- `piano-tecnico.md`: **how** to build it. Architecture, modules, flows, tests and milestones M0–M5 (§12).

Work one milestone at a time. Start a milestone only when the user asks, and don't implement anything that belongs to a later one. When a decision changes, update the spec or the plan.

**Current state**: M0 (skeleton). The integration loads, has no entities, and its config flow aborts with `not_yet_available`. Update this line at the end of each milestone.

## Conventions

- **Language**: code, identifiers, comments, logs, entity names, entity_ids and UI strings are in English. Talk to the user in Italian; the specs stay in Italian.
- **Strings**: `translations/en.json` is the only strings file. There is no `strings.json`, because the two diverged in the reference. Icons go in `icons.json`. Hassfest requires `config.step` in `en.json` as soon as there's a config flow, even if it's empty.
- **Entities**: `_attr_has_entity_name = True`, `translation_key = key`, `unique_id = f"{address}_{key}"`, with the keys from plan §6. Don't set a suggested area. If the device already has an area when its entities are created, HA puts the area in the entity_ids too (that's how the reference got `binary_sensor.taverna_pixel_led_display_connected`). Check the real entity_id in HA after adding an entity rather than deriving it from the name.
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

- Discovery: local name `LED_BLE_*` and service UUID `0000fa01-0000-1000-8000-00805f9b34fb`. The matchers go into `manifest.json` in M1, not before: otherwise HA would offer the panel in production too early.
- Write characteristic `0000fa02-0000-1000-8000-00805f9b34fb`, notify characteristic `0000fa03-0000-1000-8000-00805f9b34fb`.
- Commands are framed as `[length LE16][opcode LE16][payload]`, where the length includes the 4 header bytes. Brightness, for example, is opcode `0x8004` with a 1–100 byte, and power is `05 00 07 01 <0|1>`.
- pypixelcolor's clock command only takes a two-digit year (`DD/MM/YY`). The weekday stays right because 2000 years are whole Gregorian cycles.

### Transfers and ACKs

- Each window of a transfer is written in 244-byte chunks. On the local BlueZ adapter a single write can't exceed 512 bytes.
- After each window the panel answers `05 00 xx xx <status>`: status `0` or `1` means the window was received, `3` means the transfer is done. Wait up to 8 s for it before sending the next window.
- pypixelcolor's own transport waits for an ACK after simple commands too (power, brightness), while the reference treated it as optional. Whether every command gets one is check V9, done in M1.

### Power state

- The panel can't be asked whether the screen is on, nor its brightness: the device-info reply carries neither. HA can only show the last state it sent.
- Any content sent to the panel (an image, a GIF, the clock) turns the screen back on.
- An HA restart leaves the screen as it was, because the panel keeps its power.
- A power cycle boots the panel with the screen on, showing its built-in GIFs: the mode isn't restored.
- Every disconnect seen so far was the panel losing power.

### Reconnection quirks

- Use `bluetooth.async_register_advertisement_callback`: it fires on every advertisement, once per scanner that hears it. `async_register_callback` skips advertisements identical to the previous one, so it misses a panel that was unplugged and replugged within a few minutes.
- The callback doesn't replay past advertisements at startup: the first connection attempt must be made explicitly.
- The callback runs before the Bluetooth manager records the advertisement. A task started from it must `await asyncio.sleep(0)` before connecting, so the device can be looked up.
- After a failed attempt, wait 30 s before the next one.
- Serialize `connect` with a lock and return early when already connected, so a background reconnect and a command can't open two connections.
- pypixelcolor's own transport creates its own `BleakClient` from the address, bypassing HA's Bluetooth stack and its proxies. We only use pypixelcolor to build commands; the transport is ours.
- Connect with `establish_connection(..., ble_device_callback=...)`, so retries use the freshest `BLEDevice` (the proxy may have changed). Enable notifications once per connection: the reference restarted them for every command, which costs round trips through a proxy.
- On the user's HA the panel is reached both through a local USB adapter and through an ESPHome Bluetooth proxy.
