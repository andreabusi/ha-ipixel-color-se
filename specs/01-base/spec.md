# iPixel Color for Home Assistant: functional spec (01-base)

| | |
|---|---|
| **Status** | Done. Version 1.1, which incorporates the outcomes of V5 and V7 (F6.2, F6.5, F6.7) |
| **Date** | 2026-11-08 |
| **Release** | `v0.1.0` |
| **Domain** | `ipixel_color_se` |
| **Reference** | `ha-ipixel-color`, branch `import-server-version` (commit `a93b813` plus uncommitted changes: background reconnection, power state) |
| **Protocol library** | `pypixelcolor` 0.5.0 |

This document defines **what** the new integration must do, not **how**: the architecture and the code are in the [technical plan](plan.md). The decisions are collected in §9. Things to check on the panel are marked **[Vn]**, and their questions and outcomes are in [panel-checks.md](../panel-checks.md).

Entity names, entity_ids, UI strings and code are in English, and the document gives entity names as they appear in HA. It was written in Italian and translated on 2026-11-13. The only change in content is that the panel checks moved to `panel-checks.md`.

---

## Summary

- **What 01-base does**: screen power and brightness, clock, sending images (animated GIFs and still images), orientation, connection with automatic reconnection, diagnostics. Text comes in a later unit.
- **Entities**: 16 per display, with English names prefixed by the name you choose during setup, for example `switch.pixel_taverna_power`. The full list is in §6.
- **Clean install**: domain `ipixel_color_se`. Before adding the panel to the new integration it must be removed from the old one, and automations and dashboards must be updated by hand.
- **Immediate send**: no more Auto Update or Update Display. A change is sent to the display at once if the content it refers to is visible. For example, a clock style changed while an image is visible is applied when you go back to the clock.
- **`Mode` decides what is shown**: `Clock` or `Image`, and in the future `Text`. The `Image player` sets `Mode` to `Image`, and Stop sets it back to `Clock`.
- **Restore after every reconnection**, for example after a power cut: the integration sends the time, brightness and orientation again, turns the screen off again if it was off, and otherwise shows the last content again. The panel no longer stays on its built-in GIFs.
- **`Disconnect`** frees the panel for the phone app and turns off `Auto reconnect`. HA takes control back when you turn `Auto reconnect` on again or send a command.
- **Known limits**:
  - the panel reports neither its power state nor its brightness, so HA shows the last state it sent (with the restore this stays reliable);
  - the last image is downloaded again from its source when needed: a temporary URL that no longer exists can't be shown again.
- **Requirements**: Home Assistant 2026.10.0 or later, GPL-3.0 license, published on GitHub (HACS later).

---

## 1. Goals

1. Rewrite the integration for iPixel Color Bluetooth LED displays (sold as "B.K. Light LED Pixel Board"), starting from the existing one.
2. Expose **few, clear entities**, all recognizable as belonging to their display.
3. Keep what works well today: discovery, connection through Bluetooth proxies, automatic reconnection, GIF player, connection state.
4. Bring only reliable features into 01-base: power, brightness, clock, images (animated GIFs and still images).
5. Leave room to add text handling in a later unit without upending the entities.

**Non-goals of 01-base:** text modes (`text`, `textimage`), fonts, text colors, text animations, the `display_text` service, migration from the current integration.

---

## 2. Glossary

- **Panel / display**: the physical iPixel device.
- **Screen on/off**: the state of the LEDs, controlled over Bluetooth. The panel stays powered and connected even with the screen off.
- **Disconnection**: loss of the Bluetooth link, usually because the panel lost power.
- **Advertising**: the signal the panel transmits when it's powered and **not** connected. It's how HA notices that it's back.
- **Content**: what the panel shows: the clock, an image (animated GIF or still image), or the built-in GIFs the panel shows by itself when it starts.

---

## 3. Analysis of the reference integration

### 3.1 What works and must be kept

- **Bluetooth discovery**: HA automatically offers panels whose name starts with `LED_BLE_` or that expose the `FA01` service. Panels can also be added manually, from a list or by MAC address.
- **HA's Bluetooth stack**: the connection goes through HA, so it also works through ESPHome proxies, with automatic retries while connecting.
- **Queued commands**: one send at a time, so a GIF being transferred isn't interrupted by other commands.
- **Reliable GIF transfer**: sent in blocks, with an acknowledgment from the panel for each block.
- **Background reconnection** (recent, uncommitted change): as soon as the panel advertises again, HA reconnects. After a failed attempt it waits 30 s.
- **Connection sensor**: updates immediately, without polling.
- **GIF player**: accepts a URL, a `/local/…` path or a file from the Media browser (filtered to GIFs only). The panel loops the GIF by itself.
- **Power state** (recent change): the panel doesn't say whether the screen is on, so the integration infers it from the last command sent. The rules have already been checked on the panel (§5.5).

### 3.2 Problems found

| # | Problem | Evidence in the code | Effect for the user |
|---|---|---|---|
| P1 | **Entities without the display prefix** | No entity uses HA's mechanism that ties the name to the device, and the names are generic ("Auto Update", "Brightness", "Mode"). The power switch instead takes the device name. | The entity_ids registered with earlier HA versions are `switch.auto_update`, `number.brightness`, `select.mode`. With two displays they get `_2`. **Checked**: the problem is in the integration's code, not in an old local configuration. |
| P2 | **State scattered across entities** | Each setting is a separate entity. When updating the display, the integration reads the values back from the other entities, looking them up by ID. | Fragile: three entities (Text Animation, Text Speed, Text Rainbow) look up the others with a hand-built name that never matches the real ids, so they never trigger the automatic update. |
| P3 | **"Auto Update" + "Update Display"** | A settings change reaches the display only if the Auto Update switch is on, otherwise the button is needed. | Hard to understand: you change an option and nothing happens. |
| P4 | **Invisible errors** | Failed commands only end up in the log, and all entities always appear available. | You press a button, nothing happens, and you get no message. |
| P5 | **Startup tied to the display** | Loading the integration requires a successful connection and reading the resolution from the panel. | If the panel is off when HA starts, the integration stays in error and retries with growing delays. |
| P6 | **Diagnostic sensors of little use** | "MCU Version" and "WiFi Version" are always `unknown`, because pypixelcolor 0.5.0 doesn't decode the versions. Width, height and type are fixed data, but they're queried every 30 s, and they're "unavailable" while the panel is disconnected. | Sensors always "unknown" or "unavailable", which only add noise. |
| P7 | **Panel time** | The time is taken from the container's system, not from the time zone configured in HA. It's sent only when the clock is activated or with the button. | Wrong time if the container has a different time zone, and the time drifts after a panel restart. |
| P8 | **Brightness not reapplied** | Brightness is restored in the entity, but not sent to the panel again after a reconnection. | What you see in HA may not match the panel (see [V2]). |
| P9 | **Leftovers** | `services.yaml` declares `display_text`, which isn't implemented. The two UI strings files have diverged. Model "LED Matrix Display" and version "1.0" are hardcoded. The clock styles are named "0"–"8". | A sloppy interface. |
| P10 | **Noisy setup list** | Manual setup lists *all* nearby Bluetooth devices, with a star on the compatible ones. | A long, confusing list. |

### 3.3 Inventory of the current entities and their fate

There are 27 entities today. 16 are planned (§6).

| Current entity | Type | Fate in 01-base |
|---|---|---|
| Power (takes the device name) | switch | **Kept** as `Power` (§5.5) |
| Brightness | number | **Kept** (§5.5) |
| Mode (textimage / text / clock) | select | **Revised**: options `Clock` / `Image`, with `Text` planned for the future (§5.7) |
| Clock Style | select | **Kept**, with readable style names |
| Clock 24h, Clock Show Date | switch | **Kept** |
| Sync Time | button | **Kept**, plus automatic sync |
| GIF Player | media_player | **Extended**: becomes `Image player`, for GIFs and still images (§5.8) |
| Display Connected | binary_sensor | **Kept** as `Connected` |
| Display Width, Display Height | sensor | **Kept** as `Width` and `Height` |
| Device Type | sensor | **Moved** to the device info (model) |
| MCU Version, WiFi Version | sensor | **Removed**: always `unknown` |
| Auto Update | switch | **Removed**: every change is sent at once (§5.6) |
| Update Display | button | **Removed** |
| Display (text) | text | Later unit |
| Font, Text Size | select | Later unit |
| Font Size, Line Spacing, Text Animation, Text Speed, Text Rainbow | number | Later unit |
| Antialiasing | switch | Later unit |
| Text Color, Background Color (lights used as color pickers) | light | Later unit, with a different model |
| *(new)* Auto reconnect | switch | **New** (§5.3) |
| *(new)* Disconnect | button | **New** (§5.3) |
| *(new)* Image fit | select | **New** (§5.8) |
| *(new)* Orientation | select | **New** (§5.11) |
| *(new)* Signal strength | sensor | **New** (§5.10) |

---

## 4. Scope of 01-base

**Included**
- Setup and discovery of displays
- Persistent connection, automatic reconnection that can be turned off, manual disconnection
- Screen on/off and brightness
- Clock mode, with its options and time sync
- Image player: animated GIFs and still images, with a choice of fit
- Display orientation
- Restoring the state after a reconnection
- Diagnostics: connection, width, height, signal, diagnostics download

**Excluded** (see also §11)
- All text handling
- Panel features that pypixelcolor offers but that aren't exposed today: internal scheduling, saved slots, timers, scores, rhythm and fun modes.
- Migration from the current integration: it will be a clean install (§8)

---

## 5. Functional requirements

### 5.1 F1: Setup and discovery

- **F1.1** When HA detects an iPixel panel (name `LED_BLE_*` or service `FA01`), it offers it with the standard "New device discovered" notification.
- **F1.2** Manual setup lists **only** the iPixel panels that are visible and not configured yet. Entering the MAC address by hand is still possible.
- **F1.3** Before completing setup the integration connects to the panel and reads its type and resolution. If it can't, it shows a clear error and lets the user retry.
- **F1.4** The user names the display during setup, for example "Pixel Taverna". The suggested name is the Bluetooth one. This name becomes the prefix of every entity (§5.2).
- **F1.5** Address, name, type and resolution are saved in the configuration, so the integration can start even if the panel is off (fixes P5).
- **F1.6** Each panel is one device in HA. Several panels work independently, and the same panel can't be added twice.
- **F1.7** When the integration is removed or disabled, it closes the connection: the panel is free again for the phone app.

*Acceptance*: a powered panel near HA appears among the discovered devices with no action needed. Restarting HA with the panel off produces no loading errors.

### 5.2 F2: Device identity and entity names

- **F2.1** Entity names follow HA's standard mechanism. Each entity declares **only its own name** (`Power`, `Brightness`, `Clock style`…), with no prefix written in the code. HA combines it with the device name:
  - the displayed name becomes "Pixel Taverna Power";
  - the entity_id becomes `switch.pixel_taverna_power`.

  Fixes P1.
- **F2.2** Every entity has a name of its own: none takes just the device name, so the entity_id always says what it is.
- **F2.3** If the device is renamed in HA, the displayed entity names follow, and HA offers to update the entity_ids too.
- **F2.4** Entity names and UI strings (setup, errors) are in **English**.
- **F2.5** Entities are split into HA's standard sections: **Controls** (everyday use), **Configuration** (settings), **Diagnostic**.
- **F2.6** The device reports manufacturer, model with resolution (for example "LED Pixel Board 64×16") and Bluetooth address, so HA links it to the adapter or proxy that sees it.

*Acceptance*: with two displays configured, no entity_id lacks the prefix and none ends in `_2`.

### 5.3 F3: Connection, automatic reconnection and disconnection

- **F3.1** While the panel is reachable, the integration keeps a permanent connection. Commands run one at a time, in order of arrival.
- **F3.2** The **`Auto reconnect`** switch (Configuration, on by default) decides whether the integration reconnects by itself. Its state survives HA restarts.
- **F3.3** **On**: when the panel advertises again (typically after being plugged back in), the integration reconnects within a few seconds. After a failed attempt it waits 30 s before retrying.
- **F3.4** **Off**: after a disconnection the integration doesn't reconnect by itself. Any command sent to the display (power, brightness, mode, image…) reopens the connection.
- **F3.5** If the switch is turned back on while the panel is disconnected but visible, the connection starts at once.
- **F3.6** The **`Disconnect`** button (Configuration) closes the connection and **turns off `Auto reconnect`**, so the panel stays free for the phone app. HA takes over again in two ways: by turning `Auto reconnect` back on, or by sending a command.
- **F3.7** If HA starts while the panel is absent, the control entities are unavailable and the connection starts as soon as the panel appears (if `Auto reconnect` is on).
- **F3.8** ESPHome Bluetooth proxies remain supported.

*Acceptance*:
- I unplug the panel and plug it back in: within about 10 s of the panel restarting, `Connected` is on again without touching anything in HA.
- I press `Disconnect`: the phone app can connect to the panel and HA doesn't "steal" the connection.

### 5.4 F4: Connection state

- **F4.1** The **`Connected`** binary sensor (connectivity type, Diagnostic) is on while HA is connected to the panel, and changes state as soon as the connection drops or is restored.
- **F4.2** The sensor is always available, because its job is precisely to say whether the panel is reachable.

### 5.5 F5: Screen power and brightness

Two separate entities are kept, both in Controls:

- **F5.1** **`Power`** (switch) turns the screen on and off.
- **F5.2** **`Brightness`** (slider 1–100 %) sets the brightness. The value is applied at once. [V6]
- **F5.3** The panel doesn't report its state, so the integration shows the **last known state**, updated with these rules (already checked on the panel):
  - power on or off command → the matching state;
  - sending any content (clock, image) → on, because content turns the screen back on;
  - reconnection → the desired state is restored (§5.9);
  - HA restart → start from the saved state, because the panel doesn't change.
- **F5.4** If a brightness change turns the screen back on while it's off, `Power` must reflect it. [V1]
- **F5.5** After every reconnection the brightness is sent to the panel again (§5.9).

*Acceptance*: I turn the screen off from HA, start a GIF from the player, and `Power` is on again with no other action.

### 5.6 F6: Clock

- **F6.1** The user shows the clock by choosing `Clock` in `Mode` (§5.7).
- **F6.2** The clock options are in Configuration:
  - **`Clock style`**: the panel's styles, with descriptive names derived from [V5]. There are 8: the panel has a ninth, which will come when pypixelcolor accepts it;
  - **`Clock 24-hour format`**: on or off;
  - **`Clock show date`**: on or off.
- **F6.3** **General rule: every change is sent to the display at once**. "Auto Update" and "Update Display" no longer exist (fixes P3). If the clock is visible, a change to its options updates it immediately. If an image is visible, the change is stored and applied the next time the clock is activated. Changing a setting never changes the content shown: only `Mode` decides that.
- **F6.4** The time sent to the panel is the one of the **time zone configured in HA** (fixes P7).
- **F6.5** The time is synced automatically on every connection, every time the clock is activated, every time the screen is turned back on, once a day, and right after daylight saving changes. Scheduled syncs skip a screen that's off, because the sync would turn it back on: the time arrives when the screen is turned on. [V7]
- **F6.6** At midnight, if the clock is visible, the integration updates the date on the panel. It's harmless even if the panel advances it by itself. [V3]
- **F6.7** The **`Sync time`** button (Configuration) remains available to force a sync. If the screen is off it turns it on, and `Power` reflects that. [V7]

*Acceptance*: with HA set to Europe/Rome and the container in UTC, the panel shows Italian time. When I change the style with the clock visible, the panel updates within a couple of seconds.

### 5.7 F7: Mode (content shown)

- **F7.1** The **`Mode`** selector (Controls) says what the panel is showing, according to the last content sent by HA. The options are **`Clock`** and **`Image`**.
- **F7.2** Choosing `Clock` shows the clock with the current options. Choosing `Image` sends the last image played again, animated or still. If there's no image yet, an error asks the user to use the player.
- **F7.3** Playing an image from the player sets `Mode` to `Image`. The player's Stop sets it back to `Clock`.
- **F7.4** If HA doesn't know what the panel shows, `Mode` is "unknown".
- **F7.5** **Ready for text**: in a later unit the selector will get the `Text` option. The F6.3 rule applies to text too: its settings apply at once when the text is visible. The 01-base entities don't change.

### 5.8 F8: Image player

- **F8.1** The **`Image player`** (Controls) accepts as a source:
  - an http(s) URL;
  - a `/local/…` path;
  - a file chosen from HA's **Media browser**.

  Automations can use it too, with the standard `media_player.play_media` action.
- **F8.2** **Formats**: GIF (animated or not), PNG, JPG, WebP, BMP. These are the ones pypixelcolor 0.5.0 handles. The Media browser shows only files in these formats.
- **F8.3** **Animated GIFs** keep their frame timings and the panel loops them by itself. **Still images** stay fixed on the panel. Transparent areas become black.
- **F8.4** The **`Image fit`** selector (Configuration) decides how the image is adapted to the panel's resolution:
  - **`Fill`** (default, today's behavior): fills the screen and crops the excess, keeping the proportions;
  - **`Fit`**: shows the whole image, with black bars at the sides.

  Following the F6.3 rule, if an image is visible the change sends it again at once with the new fit. Otherwise it applies from the next image.
- **F8.5** The player's states:
  - **buffering** during the transfer;
  - **playing** while the image is on the panel;
  - **idle** when other content has replaced it.

  The title shown is the file name.
- **F8.6** *Play* sends the last image again. *Stop* goes back to the clock (§5.7).
- **F8.7** **No copy of the image**: the integration remembers only the *source* of the last image, and downloads it again when it must send it again (Play, `Mode` = `Image`, `Image fit` change, restore after a reconnection).
  - Media browser files always work, because the integration remembers their reference and not the signed URL, which expires.
  - If the source is no longer reachable (temporary URL, deleted file), a user action that asks for the image (Play, `Mode` = `Image`, `Image fit` change) fails with a visible error. The restore after a reconnection shows the clock instead (F9.4). The same applies when the image must be sent again only to turn the screen back on (`Power`, or brightness with the screen off) after the panel lost power: the screen comes on with the clock and `Mode` switches to `Clock`.
- **F8.8** A file larger than 10 MB, an unsupported format, an unreachable URL or a failed transfer produces a **visible error** in the interface (fixes P4).
- **F8.9** The last image and the player state survive HA restarts.
- **F8.10** A transfer in progress isn't interrupted. Commands that arrive meanwhile (for example brightness) run right after it.

*Acceptance*:
- I choose a GIF from the Media browser: the player goes through buffering and then playing, and the GIF runs on the panel.
- I send a JPG from a URL with `Image fit` = `Fit`: the panel shows the whole photo with black bars. I switch to `Fill` and the image is sent again, cropped.

### 5.9 F9: Restore after a reconnection

After **every** reconnection the integration brings the panel back to the state HA wants, instead of leaving it on the built-in GIFs it shows when it restarts:

- **F9.1** it syncs the time;
- **F9.2** it sends brightness and orientation again;
- **F9.3** if the screen was supposed to be off, it turns it off again, so the state shown by `Power` always matches the real one;
- **F9.4** if the screen was supposed to be on, it shows the last content again:
  - the clock;
  - or the last image, downloaded again from its source. If the source is no longer reachable, it shows the clock and sets `Mode` to `Clock`.

*Acceptance*: with the clock active I cut power to the panel and restore it. The panel shows the clock again, not the built-in GIFs. If the screen was off, it stays off.

### 5.10 F10: Diagnostics

All the following entities are in Diagnostic:

- **F10.1** **`Connected`** (§5.4).
- **F10.2** **`Width`** and **`Height`**: numbers in pixels, read once during setup. They stay available while the panel is disconnected. The resolution also appears in the device model (F2.6).
- **F10.3** **`Signal strength`**: RSSI in dBm, disabled by default. It shows whether the panel is at the edge of the proxy's range. [V4]
- **F10.4** **Download diagnostics**: HA's standard entry in the menu of the device and integration pages. It downloads a JSON file with:
  - the panel's type, resolution and address;
  - the connection state: connected or not, last disconnection, adapter or proxy used;
  - `Auto reconnect`;
  - the known power state, brightness and `Mode`;
  - the clock options;
  - `Image fit` and `Orientation`;
  - source and name of the last image.

  It lets users attach a complete picture to GitHub issues, without being asked for logs.

### 5.11 F11: Orientation

- **F11.1** The **`Orientation`** selector (Configuration) sets the display's orientation, for example if the panel is mounted upside down. The panel has 4 values. The option names are defined after check [V8], for example `Normal` and `Upside down`. The default is the normal one.
- **F11.2** It's a display setting, not a content setting: it applies at once, whatever is visible.
- **F11.3** It's sent again after every reconnection (F9.2) and survives HA restarts.

*Acceptance*: I choose the upside-down orientation and the visible content flips. After a power cut it stays flipped.

---

## 6. Entity model

Example for a display called "Pixel Taverna". Names and entity_ids are the expected ones, to be confirmed during implementation.

| Name (declared by the entity) | Type | Section | Expected entity_id |
|---|---|---|---|
| Power | switch | Controls | `switch.pixel_taverna_power` |
| Brightness | number | Controls | `number.pixel_taverna_brightness` |
| Mode | select | Controls | `select.pixel_taverna_mode` |
| Image player | media_player | Controls | `media_player.pixel_taverna_image_player` |
| Clock style | select | Configuration | `select.pixel_taverna_clock_style` |
| Clock 24-hour format | switch | Configuration | `switch.pixel_taverna_clock_24_hour_format` |
| Clock show date | switch | Configuration | `switch.pixel_taverna_clock_show_date` |
| Image fit | select | Configuration | `select.pixel_taverna_image_fit` |
| Orientation | select | Configuration | `select.pixel_taverna_orientation` |
| Auto reconnect | switch | Configuration | `switch.pixel_taverna_auto_reconnect` |
| Sync time | button | Configuration | `button.pixel_taverna_sync_time` |
| Disconnect | button | Configuration | `button.pixel_taverna_disconnect` |
| Connected | binary_sensor | Diagnostic | `binary_sensor.pixel_taverna_connected` |
| Width | sensor | Diagnostic | `sensor.pixel_taverna_width` |
| Height | sensor | Diagnostic | `sensor.pixel_taverna_height` |
| Signal strength | sensor | Diagnostic (disabled) | `sensor.pixel_taverna_signal_strength` |

---

## 7. Cross-cutting requirements

- **T1 Availability**: control entities are available when the panel is reachable, that is connected or visible over Bluetooth. This way, even with `Auto reconnect` off, a command can reopen the connection. They become unavailable when the panel is unplugged, or when it's connected to the phone app and therefore not advertising. Configuration entities are always available, because they're settings saved in HA.
- **T2 Visible errors**: every failed action (panel unreachable, transfer failed, invalid parameter) shows a message in the interface and fails the automation that started it, instead of only ending up in the log.
- **T3 Persistence**: all settings survive HA restarts: clock options, `Image fit`, `Orientation`, brightness, power, mode, last image source, `Auto reconnect`.
- **T4 No polling**: states update on events. Fixed data (resolution, type) is read once.
- **T5 A single connection**: the panel accepts one Bluetooth connection at a time. While HA is connected, the phone app can't connect. `Disconnect` makes room for it (F3.6).
- **T6 Language**: English for entity names, UI strings, logs and code.
- **T7 Compatibility**: Home Assistant **2026.10.0** or later, with no compatibility code for earlier versions. The project is published on GitHub and must meet the requirements for a possible inclusion in HACS.
- **T8 Testability**: the logic that doesn't need the panel (state rules, restore, time sync) must be verifiable with automated tests. The details are in the technical plan.
- **T9 Actions**: in 01-base the standard entity actions are enough (`switch.turn_on`, `number.set_value`, `select.select_option`, `media_player.play_media`…), with no custom actions of the integration.

---

## 8. Installation and relationship with the current integration

- **No migration**. The old integration is removed and the new one added from scratch. When the old one is removed, HA deletes its entities too, so the new entity_ids start clean.
- Automations and dashboards that use the old entities must be updated by hand.
- The domain is `ipixel_color_se`, different from the current one (`ipixel_color`), so the two integrations can be installed together. Both offer the same panel in discovery, though. Before adding the panel to the new one it must be removed from the old one, because the panel accepts a single connection (T5).
- **License**: GPL-3.0, like the reference integration we take code from, crediting its origin in the README. pypixelcolor is MIT, so compatible.

---

## 9. Decisions

### 9.1 Taken

| ID | Decision |
|---|---|
| D1 | No migration: clean install (§8) |
| D1-bis | Domain `ipixel_color_se`. Published on GitHub, installed from HACS as a custom repository (T7) |
| D2 | Two separate entities: `Power` (switch) and `Brightness` (number) (§5.5) |
| D3 | With `Auto reconnect` off, a command reopens the connection. `Disconnect` closes the connection and turns off `Auto reconnect` (§5.3) |
| D4 | After every reconnection the desired state is restored (§5.9) |
| D5 | `Mode` selector, ready for `Text` (§5.7) |
| D6 | Yes to `Signal strength` and to "Download diagnostics" (§5.10) |
| D7 | The player also supports still images, with the `Image fit` selector (§5.8). Orientation is added (§5.11) |
| D8 | The display name is asked for during setup (F1.4) |
| D9 | Home Assistant 2026.10.0 or later (T7) |
| D10 | A change to an option applies only if its content is visible: `Mode` decides what is shown (F6.3) |
| D11 | The player is called `Image player` and the `Mode` option is called `Image` |
| D12 | No copy of the image: it's downloaded again from its source (F8.7) |
| D13 | No custom actions in 01-base (T9) |
| D14 | GPL-3.0 license (§8) |
| — | Names, interface and code in English |
| — | Diagnostics with separate `Width` and `Height`, numeric in pixels (§5.10) |
| — | Every change is sent to the display at once: no "Auto Update" or "Update Display" (§5.6) |

### 9.2 Open

None.

---

## 10. Panel checks

The checks of this unit are V1–V12. Their questions, the reason for each and the outcomes are in [panel-checks.md](../panel-checks.md). None of them changed the decided features: they settled details such as option names, slider limits and how often to sync the time.

---

## 11. Future developments (outside 01-base)

- **Text.** To be redesigned from scratch: the current model (two modes, 12 setting entities, colors through lights) proved too complex. A "show text" action with few parameters, plus the `Text` option in `Mode`, will probably be enough.
- Panel features available in pypixelcolor: slots saved on the panel, internal scheduling, timers, scores, rhythm and fun modes.
