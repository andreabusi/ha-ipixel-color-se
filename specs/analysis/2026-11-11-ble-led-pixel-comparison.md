# Comparison with ha-ble-led-pixel-display

| | |
|---|---|
| **Date** | 2026-11-11 |
| **Subject** | [`sphings79/ha-ble-led-pixel-display`](https://github.com/sphings79/ha-ble-led-pixel-display) `v2.4.1`, commit `2b3fb81`: domain `ble_led_pixel`, GPL-3.0 |
| **Compared with** | `ipixel_color_se` `v0.1.0` ([01-base](../01-base/spec.md)) |

Another Home Assistant integration supports the same panels and started from the same code. This note compares its features with ours, collects what its protocol notes teach us, and lists the candidates for our next units. It's a snapshot of that repository at that commit.

## Summary

- **What it is.** A fork of `cagcoach/ha-ipixel-color` that merges the image, MDI icon and layout work of `tigers75/ha-ipixel-color`, with releases since September 2026. About 10,000 lines, for many panel models (from 16×16 to 640×64), from HA 2024.1. GPL-3.0, like this repository.
- **Entity model.** It keeps the reference's model, which 01-base dropped (spec P2, P3): a `text` entity, the colors as two `light` entities, about ten setting entities, and the `Auto Update` switch with the `Update Display` button. On top of it, it adds many actions: `send_text`, `send_layout`, `send_image_file`, `send_mdi_icon`, `show_emoji`, the gallery and slot actions, and the admin-only `send_raw_command` and `set_password`.
- **Its most valuable part** is [`docs/protocol.md`](https://github.com/sphings79/ha-ble-led-pixel-display/blob/2b3fb81/docs/protocol.md), appendices A–C: the inventory of the commands and replies, recovered by decompiling the vendor app (iPixel Color 3.7.7). Section 3 collects what matters to us.
- **Our panel.** 01-base was built and checked on a 32×32 (device type `0x81`, LED type 2). Some of their features don't exist on it.

## 1. Text

| Feature | Ours | Theirs | How they do it | Worth taking? |
|---|---|---|---|---|
| Text drawn by the panel (`text` mode) | — | ✓ | pypixelcolor's `send_text`: the panel gets a 1-bit mask per character and animates it by itself. Minimal traffic | **Yes**, it's the core of the text unit |
| Effects | — | Fixed, scroll left and right, blinking, breathing, snowflake; scroll up and down on 32×32 panels only | Laser (8) exists in the vendor app, but pypixelcolor 0.5 rejects it | Yes. On a 32×32 scroll up and down are available too |
| Speed | — | 0–100 | | Yes |
| Text and background color | — | Two `light` entities, plus the action's parameters | It's the model 01-base dropped | Yes, as action parameters |
| Color per word, `[#ff0000]ALARM[/] ok` | — | ✓ | Built into pypixelcolor 0.5. Doesn't work with variable-width fonts | Yes, it costs nothing |
| Gradients ("rainbow", codes 2–9) | — | 8, with names | The names are derived from the vendor app. They say themselves that the match with the firmware is "inferred, not proven" | To be seen on the panel first |
| Character height | — | 16/32/48/64 | The firmware works in rows of 16 px (seen on 64×16 and 64×20 panels). On a 32×32 pypixelcolor uses 32 by default | To be checked on a 32×32 |
| Fonts | — | 7 OFL pixel fonts, user fonts in `<config>/fonts`, metrics in a JSON file next to each font | pypixelcolor 0.5 ships only UNIFONT and no longer reads the metrics: they reimplemented that | Later, after seeing UNIFONT |
| Emoji in text | — | ✓ | pypixelcolor downloads them from jsDelivr (`twemoji@latest`) with a blocking call and caches them in `~/.cache` | With care: it's an external request |
| Text drawn by HA (`textimage` mode) | — | ✓ | Pillow → PNG. Several lines, automatic size, antialiasing, line spacing, any TTF font. Static | Maybe: on a 32×32 it's the only way to get 2–4 lines |
| Layout with an icon, an image and up to 4 texts | — | ✓ `send_layout` | Scrolling and blinking become a generated GIF, heavy to transfer: they raised the ACK wait to 25 s | Later |
| Updates | — | `Auto Update` switch plus `Update Display` button | Without them, text and color arrive in two writes and the panel flickers. Their README has a section about it | No: an action with all the parameters avoids the problem from the start |
| Text saved in a slot | — | ✓ | | Not now |

## 2. Everything else

| Area | Feature | Ours | Theirs | Worth taking? |
|---|---|---|---|---|
| Images | Images and GIFs | ✓ `Image player`: URL, `/local/`, Media browser, 10 MB, Fit and Fill, the V10 fix | Only `send_image_file`, from a path on disk | No, ours is more complete |
| | MDI icons | — | ✓ SVGs downloaded from jsDelivr, `resvg_py` dependency | Maybe, together with text (weather icon and temperature) |
| | Emoji as an image | — | ✓ `show_emoji` | Maybe |
| | Gallery of 159 drawings for 32×32, with a select | — | ✓ | Maybe. The license is compatible; otherwise the files go in My media |
| | Slots saved on the panel | — | ✓ save, show, delete, preload | To be evaluated (§3.5) |
| Firmware | Built-in animations, scoreboard, countdown, stopwatch | — | ✓, enabled per model from the vendor app's table | **No**: the app offers none of them on 32×32 panels |
| | Panel password | — | ✓ | No, unless needed |
| Clock | Styles, 24-hour format, date | ✓ 8 styles with names | ✓ numbered | Nothing to take. They confirm 9 styles on a 32×32, as V5 found |
| | Time sync | ✓ button and scheduled syncs | Button only | Nothing to take |
| Diagnostics | Firmware versions (`0x8005` read) | — | ✓ MCU and WiFi sensors | **Yes**, it's cheap, in the diagnostics |
| | Product ID and brand, from the advertisement | Raw data only | ✓ sensors, a Repairs issue for unknown panels, a `brands.json` downloaded daily | Only the decoding, in the diagnostics |
| | `send_raw_command`, admin only | — | ✓ | Maybe, as a development tool: panel checks through the integration's connection, through a proxy too |
| | `Connected`, `Signal strength`, diagnostics download | ✓ | — | Nothing to take |
| Connection | `Disconnect` and `Auto reconnect`, `Orientation`, restore on every connection | ✓ | Restore only after an HA restart, with one more attempt after 15 s. No orientation | Nothing to take |
| Languages | UI translations | English | English, German, French | Later, if needed |

## 3. What their protocol notes teach us

The sections of `docs/protocol.md` are cited as A.*n*, B.*n*, C.*n*.

### 3.1 ACK status 0

The vendor app reads the last byte of `05 00 <cmd> <status>` as: `0` CRC mismatch (it drops its queues and retransmits the whole payload), `1` block accepted, `2` seen only for the camera, `3` transfer complete (C.3). We, like pypixelcolor's `AckManager`, accept `0` as "window received" (`ACK_WINDOW_STATUSES` in `protocol.py`). That agrees with V5, where clock style 10 got status `0` and the panel showed nothing new. So today a rejected command or a corrupt window may count as a success.

### 3.2 Transfers

- The app requests an MTU of 512 and writes 509 bytes at a time (C.8). 01-base writes 244-byte chunks with response (plan §4.1), and measured 4.6–5.1 s per 12 KB window.
- They raised the per-window ACK wait from 8 s to 25 s after `no ack` errors with complex GIFs. 01-base waits 8 s.
- After an HA restart they often saw the panel reachable but not acknowledging its first transfer, so their restore tries once more after 15 s. 01-base repeats a failed restore before the next command (plan §4.3).

### 3.3 Reads

- **Firmware versions**: `04 00 05 80` gets `08 00 05 80 <MCU major> <MCU minor> <WiFi major> <WiFi minor>` (A.2, C.3). The app shows the MCU version as the major followed by the minor padded to two digits: 4 and 6 become `406`.
- **Device info**, the reply to `0x8001`: byte 4 is the device type. When the reply has at least 11 bytes, byte 10 is a password flag: `1` means the panel expects its password before it accepts content (C.3). A locked panel connects and acknowledges, but discards the content.
- Nothing reports power, brightness, orientation or what's shown. The app's own code confirms it (A.3, C.3).

### 3.4 Advertisement

Manufacturer data for company `0x5254` (HA's byte order: the app reads `54 52`), with a payload that starts `00 72`. Bytes 2 and 3 are the cid, each byte written in decimal (`00 07` → `0007`), byte 4 is the pid, byte 6 the device type. A B.K. Light 32×32 advertises `00 72 00 07 02 00 81`: cid `0007`, pid `02`, so product id `000702`, and type `0x81`. Some panels, such as a 64×16 B.K. Light, advertise no product id.

The app also recognizes panels by this manufacturer data, not only by name. Their manifest matches `manufacturer_id: 21076` with `manufacturer_data_start: [0, 114]`.

### 3.5 Slots

- Show: `0x8008`, a play list `LL 00 08 80 <count lo> <count hi> <slot>…`, so one slot is `07 00 08 80 01 00 <n>`. Delete one: `0x0102`. Delete all: `04 00 03 80` (A.8).
- Content sent with save slot 0, as 01-base does, halts the play list, and the panel then ignores `0x8008` until DIY mode is turned off (`05 00 04 01 00`), which restarts the play list. They probed this on a 64×20 panel.
- There are ten writable slots. Showing an empty slot cycles through the stored ones.
- **Our hypothesis**: the built-in GIFs a panel shows after a power cut are its stored-slot play list. If so, content saved in a slot would come back after a power cut even without HA. Deleting the stored slots can't be undone.

### 3.6 Text

- **Payload**: a 1-bit mask per character (rows padded to 8 px, least significant bit first) after a 13-byte properties header with the effect, speed, rainbow mode, color and optional background (C.5). The color isn't in the glyphs.
- **Effects**: 0 fixed, 1 scroll left, 2 scroll right, 3 scroll up, 4 scroll down, 5 blinking, 6 breathing, 7 snowflake, 8 laser (B.2). pypixelcolor 0.5 rejects 8, and rejects 3 and 4 on panels other than 32×32, because they can put some of them in a boot loop.
- **Rainbow mode** 0–9: 0 and 1 mean off, 2–9 are eight gradients.
- **Length**: pypixelcolor 0.5 accepts up to 500 characters, but writes their count in a single byte, so it fails above 255.
- **Character height**: pypixelcolor uses 16 on panels up to 20 px tall, and the panel's height otherwise (32 on a 32×32). They report that the firmware works in rows of 16 px.
- **Inline color tags** `[#rrggbb]…[/]`, six-digit hex only. They don't work with variable-width fonts.
- **Emoji**: pypixelcolor downloads Twemoji PNGs from `cdn.jsdelivr.net/gh/twitter/twemoji@latest` with `urllib` (5 s timeout), and caches them in `~/.cache/pypixelcolor/emojis`.
- **Fonts**: pypixelcolor 0.5 ships only UNIFONT, and no longer reads the per-height metrics in a JSON file next to a font.

### 3.7 Other commands

- `0x8007` built-in animations (index 1–20), `0x800A` scoreboard, `0x800D` countdown, `0x8009` stopwatch (C.2). The app's table gives none of them to LED type 2, the 32×32 panels.
- `0x8012` sets the weekday.
- `0x8001` has three forms in the app: the 8-byte device-info query with a language byte at byte 7, a 9-byte form for some models, and an 11-byte form `0B 00 01 80 YY MM DD WD hh mm ss` that also sets the date and time (C.2). 01-base sends the 8-byte form with the time in bytes 4–6, and the panel applies it (V3).
- Clock faces: 9 on a 32×32, as V5 found, 8 on most panels, 10 on a 32×16, 6 on a 144×16.
- Password: `0x0204` sets it, `0x0205` verifies it. Six digits on most models, four on two of them.

## 4. Candidates

### 4.1 Fixes and additions to what exists

| ID | Area | Item | What would change | Source | Cost | Proposal |
|---|---|---|---|---|---|---|
| C1 | Protocol | **ACK status 0** | Today `0` counts as "received". For the vendor app it's an error (a CRC mismatch, or a rejected command), so a rejected command looks successful | The vendor app (§3.1); consistent with V5 (style 10 → status 0) | Low | **Yes**, after a panel check |
| C2 | Transfers | ACK wait per window | 8 s today, while a window takes 4.6–5.1 s: little margin. They saw missing ACKs with heavy GIFs and moved to 25 s | Their experience and our M4 measurements | Low | Yes: a longer wait for image windows only |
| C3 | Transfers | Larger writes | We write 244-byte chunks. The app negotiates an MTU of 512 and writes 509 bytes at a time: this could cut the 22–24 s of a 59 KB GIF a lot | Their protocol notes (C.8) | Medium | Measure first, through the ESPHome proxy too |
| C4 | Restore | A failed restore with the connection still up | They retry after 15 s, because right after a restart the panel often doesn't acknowledge its first transfer. 01-base repeats the restore before the next command or on the next connection: to check what happens if neither comes | Their 2.4.0-beta.8 | Low | Check our code first |
| C5 | Diagnostics | Firmware versions | The `0x8005` read answers `08 00 05 80 <MCU> <WiFi>`. The value would go in the device's `sw_version` and in the diagnostics | The vendor app (§3.3) | Low | **Yes**, after a panel check |
| C6 | Diagnostics | Advertisement decoding | cid, pid and type can be read from the raw data (`000702` = B.K. Light 32×32), for the diagnostics and the device model | Their code, checked on a real panel (§3.4) | Low | Yes |
| C7 | Diagnostics | Password flag (byte 10 of the info) | It would explain the symptom "the panel accepts everything but shows nothing" | The vendor app (§3.3) | Low | Yes, together with C6 |
| C8 | Discovery | Manifest matchers | Today only the name matches. Add the manufacturer data matcher (`21076`, `[0, 114]`), and drop the `fa01` one, which never fires | Them and the vendor app (§3.4) | Low | Yes, low priority |
| C9 | Text | 255-character limit | pypixelcolor declares 500 characters, but writes their count in a single byte: over 255 it fails | pypixelcolor 0.5.0's code (§3.6) | — | To note in the text unit's spec |

### 4.2 New features

| ID | Area | Item | Notes | Cost | Proposal |
|---|---|---|---|---|---|
| N1 | Text | **"Show text" action drawn by the panel**, with the `Text` option in `Mode` and the restore | Parameters: text, color, background, effect, speed. The panel animates by itself and the traffic is minimal | Medium | **Yes**, it's the core of the text unit |
| N2 | Text | Color per word, `[#ff0000]ALARM[/]` | Already works with pypixelcolor 0.5 | None with N1 | Yes |
| N3 | Text | Scroll up and down | pypixelcolor allows them only on a 32×32, the panel 01-base was checked on | None with N1 | Yes, after seeing them |
| N4 | Text | Character height, 16 or 32 | The firmware works in rows of 16 px. What a 32×32 shows is unknown | Low | After a check |
| N5 | Text | Gradients (8, codes 2–9) | The names are derived, and the match with the firmware isn't proven | Low | After a check |
| N6 | Text | More fonts: 7 OFL pixel fonts, with their metrics in JSON | pypixelcolor 0.5 has only UNIFONT | Medium | Later, after seeing UNIFONT |
| N7 | Text | Emoji in text | pypixelcolor downloads them from jsDelivr with a blocking call: an external request, to run outside the event loop | Low | To decide |
| N8 | Text | Text drawn by HA: several lines, static, any font | On a 32×32 it's the only way to get 2–4 lines, for example "21.5°" above "45%" | Medium-high | Maybe, as a second part of the text unit |
| N9 | Text | Layout with an icon, an image and up to 4 texts, with scrolling and blinking | It becomes a generated GIF, heavy to transfer | High | Later |
| N10 | Images | MDI icons | Needs the `resvg_py` dependency, and downloads the SVGs from jsDelivr | Medium | Maybe, with N8 or N9 |
| N11 | Images | Emoji as an image | | Low-medium | Maybe |
| N12 | Images | Gallery of 159 drawings for 32×32 | Compatible license (GPL-3.0, like ours). Alternatively the files go in My media and the `Image player` shows them | Medium | To decide |
| N13 | Panel | Saved slots: save, show, delete | Hypothesis: after a power cut the panel would restart with our content, even without HA (§3.5). Deleting slots can't be undone | Medium | A check first |
| N14 | Panel | Password: set it and send it | Only needed if someone locks the panel from the app | Low | Later, if needed |
| N15 | Tools | `send_raw_command`, admin only | Panel checks through the integration's connection, through a proxy too, without disconnecting it | Low-medium | Maybe |
| N16 | Panel | Built-in animations, scoreboard, countdown, stopwatch | The vendor app offers none of them on 32×32 panels | — | **No** |
| N17 | Other | Test pattern, dimensions set by hand, `brands.json` downloaded daily, Repairs issue for unknown panels | Not needed for a known panel, and the daily download is an external request | — | **No** |
| N18 | Other | German and French translations | | Low | Later, if needed |

## 5. Suggested order

1. **One session of panel checks**, covering C1 and C5 and the text questions (N3, N4, N5, N7, N13).
2. **A fixes release**: C1, C2, C4, C5, C6, C7 and C8. C3 only if the measurements justify it.
3. **The text unit**, with N1, N2 and N3, writing its spec with what the checks found.

On 2026-11-13, C1–C8 were chosen for the `02-fixes` unit. C9 waits for the text unit.
