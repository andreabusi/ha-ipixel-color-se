# Panel checks

| | |
|---|---|
| **Updated** | 2026-11-13 |
| **Next ID** | V13 |

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

The sections below cite the 01-base documents as "spec §n" and "plan §n".

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
