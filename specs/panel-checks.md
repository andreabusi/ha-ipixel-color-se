# Panel checks

| | |
|---|---|
| **Updated** | 2026-11-15 |
| **Next ID** | V19 |

Questions that only the real panel can answer, and what it answered. Each check belongs to a unit, whose spec and plan cite it by ID. IDs are global and never reused (see the [rules](README.md#rules)).

The checks are run by the maintainer, who looks at the panel and cuts its power, together with scripts that talk to the panel directly or through the integration. [CLAUDE.md](../CLAUDE.md) describes how. Unless a check says otherwise, the panel is a 32×32 (type `0x81`).

## Index

| ID | Topic | Unit | Date |
|---|---|---|---|
| [V1](#v1-brightness-with-the-screen-off) | Brightness with the screen off | 01-base, M2 | 2026-11-07 |
| [V2](#v2-brightness-after-a-power-cut) | Brightness after a power cut | 01-base, M2 | 2026-11-07 |
| [V3](#v3-date-and-time-at-midnight-and-after-a-power-cut) | Date and time at midnight and after a power cut | 01-base, M3 | 2026-11-07 |
| [V4](#v4-advertising-while-connected) | Advertising while connected | 01-base, M1 | 2026-11-07 |
| [V5](#v5-clock-styles) | Clock styles | 01-base, M3 | 2026-11-07 |
| [V6](#v6-brightness-0) | Brightness 0 | 01-base, M2 | 2026-11-07 |
| [V7](#v7-time-sync-and-the-content-shown) | Time sync and the content shown | 01-base, M3 | 2026-11-07 |
| [V8](#v8-orientation-values) | Orientation values | 01-base, M2 | 2026-11-07 |
| [V9](#v9-acks-for-simple-commands) | ACKs for simple commands | 01-base, M1 | 2026-11-07 |
| [V10](#v10-gifs-frozen-on-their-first-frame) | GIFs frozen on their first frame | 01-base, M4 | 2026-11-08 |
| [V11](#v11-image-after-turning-the-screen-off-and-on) | Image after turning the screen off and on | 01-base, M4 | 2026-11-08 |
| [V12](#v12-time-sync-with-an-image-on-screen) | Time sync with an image on screen | 01-base, M4 | 2026-11-08 |
| [V13](#v13-ack-status-0) | ACK status 0 | 02-fixes, M6 | 2026-11-15 |
| [V14](#v14-firmware-read) | Firmware read | 02-fixes, M7 | 2026-11-15 |
| [V15](#v15-password-flag-of-an-unlocked-panel) | Password flag of an unlocked panel | 02-fixes, M7 | 2026-11-15 |
| [V16](#v16-advertisement-layout) | Advertisement layout | 02-fixes, M7 | 2026-11-15 (USB adapter) |
| [V17](#v17-ack-timings-of-a-transfer) | ACK timings of a transfer | 02-fixes, M6 | 2026-11-15 |
| [V18](#v18-write-size) | Write size | 02-fixes, M8 | 2026-11-15 (USB adapter) |

The sections of V1–V12 cite the 01-base documents as "spec §n" and "plan §n". Those of V13 and later cite the [02-fixes plan](02-fixes/plan.md).

## Checks

### V1: Brightness with the screen off

- **Question**: with the screen off, does a brightness command turn the screen back on?
- **Why**: spec F5.4.
- **Outcome** (2026-11-07): a brightness command **turns the screen back on**. So does orientation. Both therefore set `power` to true (plan §5), and in the restore the screen-off command goes last (plan §4.3). V7 confirmed that `set_time` does it too.

### V2: Brightness after a power cut

- **Question**: does the brightness stay set after the panel lost power?
- **Why**: it confirms whether the restore of the brightness (spec F9.2) is useful.
- **Outcome** (2026-11-07): the brightness **persists** after a power cut. With `Disconnect` active, the panel restarted with its built-in GIFs already dimmed, and the following restore changed nothing. Restoring the brightness is still useful for changes made elsewhere, for example from the app.

### V3: Date and time at midnight and after a power cut

- **Question**: in clock mode, does the date advance by itself at midnight? Is the time kept after a panel restart?
- **Why**: confirmation only, because spec F6.5 and F6.6 already cover both cases.
- **Outcome** (2026-11-07): at midnight the panel advances the date and the weekday by itself. Without power, instead, it loses time and date: it restarts from about 08:00:00, and byte 8 of the info frame, which is the month, goes back to 0 until a clock command sets the date again. Bytes 5 and 6 are the minutes and seconds just set. The restore covers everything: `set_time` at step 1, the clock at step 5 (plan §4.3).

### V4: Advertising while connected

- **Question**: does the panel keep advertising while it's connected?
- **Why**: if it stops, `Signal strength` updates only while the panel is disconnected (spec F10.3).
- **Outcome** (2026-11-07): while connected the panel **stops** advertising, and starts again at once, several times a second, as soon as the connection closes. So `Signal strength` updates only while the panel is disconnected. The reachability computed from advertisements must be ignored while the panel is connected, because HA's Bluetooth manager eventually considers it unavailable (plan §4.2).

### V5: Clock styles

- **Question**: what do the 9 clock styles look like?
- **Why**: to give them descriptive names (spec F6.2).
- **Outcome** (2026-11-07): on the 32×32 the valid styles are the values 1–9. 0 gets the ACK with status 1 but shows nothing (the previous content stays), and 10 gets status 0. All styles alternate two screens: the date (the weekday in pink, month.day in light blue, about 5 s) and the time (about 10 s), which changes by style:
  - 1–3: a planet with the hour above and minutes.seconds below, in yellow, gradient or blue;
  - 4–6: a dashed frame, gradient, yellow or one color per side;
  - 7–9: HH:MM above, and an hourglass with the seconds below, with yellow, orange or white sand.

  pypixelcolor accepts 0–8, so we use 1–8, with default 1 and the names of plan §6.

### V6: Brightness 0

- **Question**: what does brightness 0 do? pypixelcolor accepts it, while the reference starts from 1.
- **Why**: the lower limit of `Brightness`.
- **Outcome** (2026-11-07): brightness 0 doesn't turn the screen off: it leaves a minimal light, to the eye the same as 1. The minimum of `Brightness` stays 1.

### V7: Time sync and the content shown

- **Question**: does the time sync cause flicker or redraw the content?
- **Why**: how often the time can be synced (spec F6.5).
- **Outcome** (2026-11-07): `set_time` causes no flicker and doesn't bring up the built-in GIFs: it restarts the clock's cycle from the date screen. With the screen off it **turns it back on**, showing the clock. So scheduled syncs skip a screen that's off, and turning the screen on (from brightness or orientation too) sends `set_time` and the clock (plan §5).

### V8: Orientation values

- **Question**: what do the 4 orientation values do? Does changing the orientation redraw the visible content at once?
- **Why**: the names of the `Orientation` options (spec F11.1).
- **Outcome** (2026-11-07): the four values rotate the content: 0 is normal, 1 rotates it by 90° counterclockwise (the top side goes to the left), 2 by 180°, 3 by 90° clockwise. The visible content rotates at once, without being redrawn. The options were named accordingly (plan §6).

### V9: ACKs for simple commands

- **Question**: do simple commands (power, brightness, orientation, time) also get an acknowledgment from the panel?
- **Why**: the reliability of visible errors (spec T2). pypixelcolor's transport waits for an ACK for simple commands too, while the reference treated it as optional. A command that didn't answer couldn't wait for an ACK, and would be considered successful after the write.
- **Outcome** (2026-11-07): brightness, orientation, power on, power off and the clock get the ACK `05 00 <id> <type> 01`, which echoes bytes 2–3 of the command. `set_time` gets the info frame `0c 00 01 80 <type> …` instead: pypixelcolor's `set_time`, which waits for an ACK, would always time out. The panel is type `0x81`, that is 32×32.

### V10: GIFs frozen on their first frame

- **Question**: why does a GIF with few colors stay frozen on its first frame? The question came up in the M4 tests.
- **Why**: spec F8.3.
- **Outcome** (2026-11-08): a 4-frame GIF stayed on its first frame, with timings of 1 s, 0.5 s or 0.2 s, while a 36-frame one at 80 ms ran. The difference was in the color tables: pypixelcolor saves the first frame with a global table sized to its colors (64) and the others with local tables (128). With equal tables (4 and 4, or 256 and 256) or smaller local ones (a global 256, locals of 4) the GIF runs. So the panel freezes on the first frame whose local table is **larger** than the global one. `protocol.image` always pads the global table to 256 colors (plan §8): with this fix the 4-frame GIF runs with its timings.

### V11: Image after turning the screen off and on

- **Question**: after turning the screen off and on by command, does the panel still show the image?
- **Why**: when turning the screen on must resend the image (spec F5.3, F8.7).
- **Outcome** (2026-11-08): with a GIF on screen, turned off and on by command, the panel **keeps** the GIF: with just `power on` it runs again, and brightness with the screen off turns it back on too. The GIF keeps going even with the screen off: it reappeared from the second frame. After a power cut, instead, the panel shows its built-in GIFs. So turning the screen on resends the image only if the panel didn't receive it on the current connection (plan §5).

### V12: Time sync with an image on screen

- **Question**: does the time sync replace an image with the clock?
- **Why**: the time sync with `Mode` = `Image` (spec F6.5).
- **Outcome** (2026-11-08): `set_time` with a GIF on screen doesn't show the clock: the GIF stays and nothing changes. Scheduled syncs and `Sync time` are fine with `mode == Image` too.

### V13: ACK status 0

- **Question**: which commands get status `0`, and what does the panel show then? Try clock style 10, orientation 4, brightness 101 and 255, and a PNG transfer with a wrong CRC, followed by the same transfer with the right one. Does any command that works get `0`? Does a rejected transfer work when it's sent again?
- **Why**: C1 (02-fixes plan §3.1): whether status `0` can be treated as an error, and whether a rejected transfer is worth one more attempt.
- **Outcome** (2026-11-15, through the USB adapter, with the clock on screen before each command):
  - **Status `0`** for brightness 101 and 255, orientation 4, clock style 10 (as in V5), a PNG with a wrong CRC, and a 3-window GIF with one byte flipped in its second window and the right CRC in the header. Each time the panel kept the clock and didn't restart.
  - In the corrupted GIF, windows 0 and 1 got `1` and only the last one got `0`. The panel checks the CRC once the whole file is in, so a rejected transfer shows only in the last ACK.
  - **Every valid command** the integration sends got `1`: orientation 0–3, power off and on, brightness 1, 20, 50 and 100, clock styles 1–8 in 24-hour format, style 1 in 12-hour format with the date, and the windows of PNGs and GIFs. `set_time` got its info frame. No valid command got `0`.
  - **Sent again** intact right after its rejection, on the same connection, the GIF got `1`, `1`, `3`, and the panel showed it, animated. So one more attempt at a rejected transfer works.

### V14: Firmware read

- **Question**: does the panel answer `04 00 05 80` with `08 00 05 80 <MCU major> <MCU minor> <WiFi major> <WiFi minor>`, how fast, and with what values? Does the read change what the screen shows?
- **Why**: C5 (02-fixes plan §3.5).
- **Outcome** (2026-11-15, through the USB adapter): the panel answers in 30–60 ms with `08 00 05 80 0b 03 07 02`, that is MCU 11.03 and WiFi 7.02, also after a power cut. The WiFi version isn't zero. The read doesn't change the screen: the clock stayed for 10 s before it and 15 s after it, on the same connection.
  - What does change the screen is **a new connection**. Each time a client connects and enables notifications, the panel shows a chain-link icon and then its built-in GIFs, unless content arrives right away: a clock sent 0.1 s after connecting stayed on screen. Disconnecting changes nothing. The integration's restore always sends content or turns the screen off, but a restore that fails leaves the built-in GIFs on screen.

### V15: Password flag of an unlocked panel

- **Question**: is byte 10 of the info frame `0` on a panel without a password, after a power cut too? The locked case isn't checked: it would mean locking the panel.
- **Why**: C7 (02-fixes plan §3.7): a byte that isn't `0` on an unlocked panel would make the flag useless.
- **Outcome** (2026-11-15, through the USB adapter): the info frame has 12 bytes, for example `0c 00 01 80 81 1d 37 00 00 01 00 01`, and **byte 10 is `0`** in every reply, before and after a power cut. Bytes 9 and 11 were always `01`.
  - Byte 8, which V3 read as the month, was `0` after the power cut and `0b` (11) after a clock command, and it went back to `0` after any image transfer, even a rejected one.

### V16: Advertisement layout

- **Question**: does the panel's manufacturer data, through the USB adapter and through the ESPHome proxy, have the layout the comparison describes (`00 72 <cid> <pid> <?> <type>`)? It's read from HA's Bluetooth diagnostics, with no action on the panel.
- **Why**: C6 and C8 (02-fixes plan §3.6, §3.8).
- **Outcome**, through the USB adapter (2026-11-15): the manufacturer data of company 21076 is `00 72 00 07 02 00 81`, the layout the comparison describes: cid `0007`, pid `02`, so product id `000702`, and type `0x81`. Byte 5 is `00`. The panel advertises no service UUID.
  - No Disconnect was needed. HA's Bluetooth keeps the last advertisement from before the connection, while the panel is connected and silent (check V4), so the integration reads the product id from it at startup too.
- **Outcome through the ESPHome proxy**: not run yet. The proxy was offline.

### V17: ACK timings of a transfer

- **Question**: in an image transfer, how long after its last write does each window's ACK arrive, and the final one? With a small PNG and a 59 KB GIF, through the USB adapter and through the ESPHome proxy.
- **Why**: C2 (02-fixes plan §3.2): the ACK timeout of transfers.
- **Outcome**, through the USB adapter (2026-11-15), with 244-byte writes:
  - Every window's ACK, and the final one, came **15–47 ms** after the window's last write returned, for a 286-byte PNG and for a 58 KB GIF in 5 windows. The 4.7–5.4 s of a 12 KB window are all writing.
  - When the panel gets the same file again, every window gets status `3`, not only the last one. That happened with the 58 KB GIF sent twice in a row.
- **Outcome through the ESPHome proxy** (2026-11-15, through the integration, from its debug log, with the proxy's WiFi working well): three different 58 KB GIFs in 5 windows took 24.6–25.0 s each, and every ACK came **0–48 ms** after the window's last write returned. A 9.4 KB GIF in one window took 4.0 s. So the time goes into the writes on both paths, and the ACK wait is short whenever the path works.
  - On 2026-11-08, with the proxy's WiFi weak, two image transfers had no ACK within 8 s (02-fixes plan §2). How late those ACKs were, if they came at all, wasn't logged.

### V18: Write size

- **Question**: what write size does each path allow (the MTU through the proxy, the characteristic's limit on BlueZ)? How long does a 12 KB window take with 244-byte writes, with the allowed size, and with 509 bytes? Does every transfer still succeed?
- **Why**: C3 (02-fixes plan §3.3).
- **Outcome**, through the USB adapter (2026-11-15):
  - bleak reports `mtu_size` 23 and a `max_write_without_response_size` of 20 for the write characteristic, so on BlueZ neither gives the real limit.
  - Writes of 509 bytes, with response, work anyway. The 58 KB GIF took 20.0 s, against 23.5 and 24.9 s with 244-byte writes, and a 12 KB window took 4.1–4.6 s instead of 4.7–5.4 s. Every transfer succeeded.
- **Outcome through the ESPHome proxy**: not run yet.
