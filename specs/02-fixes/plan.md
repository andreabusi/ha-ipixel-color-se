# iPixel Color SE: technical plan (02-fixes)

| | |
|---|---|
| **Status** | In progress |
| **Date** | 2026-11-15 |
| **Release** | `v0.2.0` (D15) |
| **Input** | The [01-base spec](../01-base/spec.md) and [plan](../01-base/plan.md), and C1–C8 of the [2026-11-11 comparison](../analysis/2026-11-11-ble-led-pixel-comparison.md) |

This unit fixes and completes what 01-base built, with the candidates C1–C8 found by comparing our integration with `ha-ble-led-pixel-display`. It adds no entity, no option and no action, so it has no spec: §1 lists what changes for the user. Section numbers like "plan §4.3" refer to the 01-base plan, and C*n* to the comparison.

---

## Summary

- **Rejected commands become errors (C1).** The panel answers status `0` when it doesn't accept a command. Today we take it as a success.
- **Transfers wait longer for their ACKs (C2)**, with timings in the debug log to choose how long.
- **A failed restore is retried after 15 s (C4)**, instead of waiting for the next command.
- **Panel identity (C5–C7):** the firmware version, read with a command the panel answers, goes in the device page and the diagnostics. The product id comes from the advertisement, and the password flag from the info frame.
- **Discovery by manufacturer data (C8)**, besides the name.
- **Write size (C3):** measured first. It changes only if larger writes are clearly faster and reliable on both paths, the USB adapter and the ESPHome proxy.
- **Three milestones**, M6–M8, and six panel checks, V13–V18.

---

## 1. What changes for the user

| Change | 01-base requirement it extends |
|---|---|
| A command the panel rejects fails with `command_failed`, in the UI and in automations, instead of looking successful | T2 |
| Image transfers through a slow path fail less often with "didn't acknowledge" | F8.8 |
| After a failed restore, the panel is put right within about 15 s, even if no command follows | F9 |
| The device page shows the panel's firmware version and its product id (for example `000702`) | F2.6 |
| The diagnostics add the firmware versions, the advertised identity, the password flag and the size of the writes | F10.4 |
| A password-locked panel logs a warning that explains why it ignores commands | T2 |
| A panel with the vendor's manufacturer data is discovered even if its name doesn't start with `LED_BLE_` | F1.1 |

---

## 2. What the logs showed

The log of the maintainer's HA, from 2026-11-08, while the panel was reached through the ESPHome proxy and the proxy's WiFi was weak:

- Two image transfers stopped with `didn't acknowledge image within 8.0 s`. One came from `play_media` at 16:59:09, the other from a restore at 17:00:12.
- That restore failed while the connection stayed up until 17:01:39. For a minute and a half the panel wasn't restored, and nothing would have tried again before the next command (C4).
- The same day's `Task exception was never retrieved` errors aren't an integration bug. They're our translated errors, from `play_media` calls that an external tool made through HA's REST API. The API shields the service call: when the HTTP request ends first, the call goes on by itself, and when it fails nobody retrieves its error. This is out of scope.

---

## 3. Design

### 3.1 ACK status 0 (C1)

**Today**: `ACK_WINDOW_STATUSES = {0, 1}` in `protocol.py`. `IPixelConnection._async_wait_ack` returns on `0`, `1` or `3`, and ignores other statuses until the timeout. The vendor app reads `0` as a CRC mismatch, and V5 saw it for the invalid clock style 10, which the panel didn't show.

**Change**:
- `protocol` names the statuses: `ACK_OK = 1`, `ACK_DONE = 3`, `ACK_REJECTED = 0`.
- An ACK of the command being waited for with status `0` raises `IPixelRejectedError`, a subclass of `IPixelCommandError`, at once, without waiting for the timeout. That holds for a simple command, for a window and for the final ACK of a transfer.
- The controller already turns `IPixelCommandError` into `command_failed`, whose message ("… didn't accept the command: …") fits. No new translation key is needed.
- **Retry**: the vendor app sends a rejected transfer again from the start. V13 showed that a transfer with a corrupted window gets `0`, at its last window because the panel checks the CRC once the whole file is in, and that sending it again works. So `IPixelConnection` restarts a rejected transfer from its first window, once. A transfer is a plan with a final ACK. A simple command is never retried, because a rejected value stays rejected.
- Status `2`, which the app sees only for its camera stream, stays ignored as today.

**Risk**: a command that works but gets `0` would start failing. V9 (simple commands), V5 (clock styles 1–9) and M4 (image windows, `05 00 03 00 01`) only ever saw `1` and `3` for valid commands, and V13 checks again every command we send.

### 3.2 ACK wait for transfers (C2)

**Today**: `ACK_TIMEOUT = 8.0` for every ACK, counted from the end of the window's writes. Through the USB adapter a 12 KB window takes 4.6–5.1 s in all, writes included. The ACK wait itself was never measured.

**Change**:
- **Timings in the debug log**: for each window of a transfer, the time spent writing and the time waiting for the ACK, and the same for the final ACK. They're needed by V17 and stay as a diagnostic aid.
- **A timeout per plan**: `SendPlan` gets `ack_timeout`. It stays 8 s for simple commands, which answer in about 30 ms (V9). `protocol.image` sets a longer one for its windows and its final ACK, `TRANSFER_ACK_TIMEOUT` = 20 s. V17 measured 0–48 ms through both paths while they work, so the value is only for a degraded path: through the proxy with a weak WiFi link, on 2026-11-08, two waits went past 8 s and weren't measured. 20 s stays, as proposed. The wait starts when the window's writes return, so slow writes don't use it up.
- A really lost ACK then holds the lock, with the player in buffering, for up to 20 s per window instead of 8. Simple commands keep failing fast.

### 3.3 Write size (C3)

**Today**: each window is written in 244-byte chunks (pypixelcolor's `chunk_size`), with response. The vendor app negotiates an MTU of 512 and writes 509 bytes at a time. On the local adapter BlueZ accepts a single write of up to 512 bytes. The characteristic accepts writes with and without response.

**Investigation (V18)**, before any change:
- The size each path allows. bleak's `mtu_size` always returns 23 on BlueZ: the characteristic's `max_write_without_response_size` gives the real value there. Through the ESPHome proxy `mtu_size` is the negotiated one.
- The time of a 12 KB window with 244-byte writes, with the allowed size, and with 509 bytes, with response. Without response only if those numbers leave the doubt that it matters, because lost packets would corrupt the window.
- Through the USB adapter with a probe script, through the proxy with a temporary build that changes the chunk size, as V6 was done.

**Change**, only if one size is clearly faster on both paths and every transfer still succeeds: `IPixelConnection` derives the chunk size from what the connection allows, capped at the measured size. In any case the allowed size goes in the diagnostics (`connection.write_size`). If nothing changes, the numbers are recorded in the outcomes, and that closes C3.

### 3.4 Retrying a failed restore (C4)

**Today**: when the restore after a background connection fails, `_async_reconnect` logs a warning and leaves `_needs_restore` set. The restore runs again before the next command, or at the next scheduled sync, which can be hours later. The same goes for the image that a restore leaves for after HA's startup (`_async_show_late_image`): if it fails, nothing tries again.

**Change**:
- When a background restore, or the late image, fails and the panel is still connected, the controller schedules one retry after 15 s (`RESTORE_RETRY_DELAY`) with `async_call_later`.
- The retry takes the lock like any operation. It does something only if the restore is still needed and the panel is still connected: a command may have restored the panel meanwhile, and after a disconnection the next connection restores it anyway.
- If the retry fails too: a warning, and the rule of plan §4.3 applies (the restore runs before the next command).
- A late image that fails also marks the restore as needed, as a failed `Image fit` already does: a transfer that fails halfway may leave anything on the panel. So the retry, or else the next command, runs the whole restore, image included.
- The timer is cancelled on disconnection. Unloading disconnects, so that cancels it too.
- Until the restore works, the panel may show its built-in GIFs: a new connection brings them up unless content follows at once (V14).
- A restore that fails inside a command is not retried: the command fails, and the user sees the error.

### 3.5 Firmware version (C5)

- `protocol.firmware_versions()` builds the request `04 00 05 80`, which expects a response. `protocol.parse_firmware_versions(frame)` reads `08 00 05 80 <MCU major> <MCU minor> <WiFi major> <WiFi minor>` and formats each version as the app does, with the minor on two digits: 4 and 6 become `4.06`. pypixelcolor has no command for it, so `protocol` builds the bytes itself.
- **When**: once per connection, right after the restore. It's not part of the restore: if the panel doesn't answer or the frame is unexpected, the controller logs at debug and doesn't ask again until HA restarts, so a panel without this command doesn't cost 8 s on every connection.
- **Where**: the MCU version becomes the device's `sw_version`, updated in the device registry only when it changes. Both versions go in the diagnostics, with the raw frame. The WiFi version goes only in the diagnostics: a panel without WiFi probably reports zeros (V14).
- The 01-base spec dropped the "MCU Version" and "WiFi Version" sensors because they were always `unknown` (P6). There is still no sensor: the version is fixed data, and it belongs on the device page.

### 3.6 Product id from the advertisement (C6)

- `protocol.parse_advertisement(manufacturer_data)` decodes the data of company `0x5254` (21076) whose payload has `0x72` at offset 1 (comparison §3.4):
  - the cid is bytes 2 and 3, each written in decimal and padded to 4 digits (`00 07` → `0007`);
  - the pid is byte 4, on 2 digits, or 3 from 100 up;
  - the device type is byte 6.

  The product id is the cid followed by the pid, for example `000702`. Anything else returns `None`: some panels advertise no product id.
- **Where it's read**: in the controller's advertisement callback, which already gets every advertisement, and in the config flow's discovery.
- **Where it's kept**: in `entry.data` (`product_id`), written the first time it's seen and only when it changes. The panel is silent while connected (V4), so it must be known without an advertisement, and across restarts. Existing entries get it from the first advertisement after the update.
- **Where it's shown**: the device's `model_id` in the device registry, and the diagnostics, with cid, pid and the advertised type. The model stays `LED Pixel Board W×H`, and there's no brand table (N17).

### 3.7 Password flag (C7)

- `parse_panel_info` also returns `password_protected`. It comes from byte 10 of the info frame when the frame has at least 11 bytes (`1` means locked), and is `None` for a shorter frame.
- The controller reads it from every reply to `set_time`, which the restore and the syncs already receive and today ignore.
- **When it's set**: one warning per connection ("… is locked with a password from the phone app, and ignores commands until it's removed"), and the flag in the diagnostics. Commands don't fail because of it (D16): the locked case can't be checked without locking the panel, and a misread flag would block every command.
- Unlocking (N14) is out of scope.

### 3.8 Discovery by manufacturer data (C8)

- **Manifest**: one more `bluetooth` matcher, `{"manufacturer_id": 21076, "manufacturer_data_start": [0, 114], "connectable": true}`. The two existing matchers stay (D17): the comparison suggested dropping the `fa01` one, but it costs nothing and may match a model we haven't seen.
- **Config flow**: `is_ipixel` accepts the same manufacturer data, with the constants `MANUFACTURER_ID` and `MANUFACTURER_DATA_START` in `const.py`.
- **No duplicates**: a panel that matches several matchers still gets one discovery flow, because the flow's unique id is the address.

### 3.9 Diagnostics

The JSON gains:
- `panel.firmware` (`mcu`, `wifi`, raw frame);
- `panel.advertised` (`cid`, `pid`, `product_id`, `device_type`);
- `panel.password_protected`;
- `connection.write_size`.

The snapshot is regenerated, and the diff reviewed.

---

## 4. Panel checks

The questions are in [panel-checks.md](../panel-checks.md), as V13–V18. One probe session through the USB adapter, at the start of M6, covers V13, V14, V15 and the adapter part of V17 and V18, so the integration is disconnected only once. V16 comes from HA's Bluetooth diagnostics. The proxy parts of V17 and V18 go through the integration, with M6's timings and a temporary build in M8.

| Check | Question, in short | Needed by |
|---|---|---|
| V13 | Which commands get status `0`, and does a rejected transfer work when sent again? | C1 |
| V14 | Does the panel answer the firmware read, and with what? | C5 |
| V15 | Is byte 10 of the info frame `0` on an unlocked panel? | C7 |
| V16 | Does the advertisement have the expected layout through both paths? | C6, C8 |
| V17 | How long after its writes does each window's ACK arrive? | C2 |
| V18 | What write size does each path allow, and how fast is each size? | C3 |

---

## 5. Tests

| File | What changes |
|---|---|
| `tests/common.py` | `FakePanel` answers the firmware read with a `firmware_frame`, can reject given commands with status `0`, has an info frame with the password flag, and its client reports a write size |
| `test_protocol.py` | Status names. Firmware request bytes and parsing. Advertisement decoding: the B.K. Light example, a pid from 100 up, no product id, another company, a short payload. The password flag, with a short frame too. `ack_timeout` of the image plan. |
| `test_connection.py` | Status `0` fails at once, for a command, a window and the final ACK. The retry of a rejected transfer, if adopted. The per-plan timeout. The write size, and the chunks derived from it if C3 changes them. |
| `test_controller.py` | Retry after 15 s of a failed restore: success, second failure, cancelled by a disconnection, skipped when a command restored the panel first. Retry of the late image. Firmware read after the restore, its failure ignored and not repeated. `sw_version` and `model_id` in the device registry. `product_id` written to `entry.data` once, and again only on a change. The password warning, once per connection. |
| `test_config_flow.py` | A discovery by manufacturer data with another name. The manual list includes it. |
| `test_diagnostics.py` | The new fields, in the snapshot |

As in 01-base, failures under frozen time are simulated with `write_error`, not with a missing ACK.

---

## 6. Work plan

Every milestone ends with green tests, a deploy to the maintainer's HA and a real test.

| # | Milestone | Content | Panel checks | Done when |
|---|---|---|---|---|
| **M6** | Reliability | C1, C2, C4: status names and rejections, per-plan ACK timeout, timings in the debug log, retry of a failed restore | **V13**, **V17**, plus the probe session of §4 | A rejected command fails visibly. A 59 KB GIF through the proxy arrives without ACK timeouts. A failed restore is retried (tests), and power cuts and HA restarts still restore the panel. |
| **M7** | Panel identity | C5, C6, C7, C8, diagnostics | **V14**, **V15**, **V16** | The device page shows the firmware version and the product id. The diagnostics have the new fields. Discovery by manufacturer data works in the tests and doesn't duplicate the panel in HA. |
| **M8** | Write size and release | C3: measurement, and a change only if justified. README, `CLAUDE.md`, version `0.2.0`, tag, installation from HACS on the maintainer's HA | **V18** | The numbers and the decision are in the outcomes. `v0.2.0` runs on the maintainer's HA from HACS. |

M6 comes first because C1 and C2 change the ACK handling that the rest relies on. M8 comes last because it's the only one whose outcome may be "no change".

### Milestone outcomes

The outcomes of the panel checks are in [panel-checks.md](../panel-checks.md).

| Milestone | Date | Outcome |
|---|---|---|
| **M6** | 2026-11-15 | **Probe session** through the USB adapter, one step at a time with the maintainer watching the panel: V13, V14, V15, and the adapter part of V17 and V18. A new connection brings up the built-in GIFs unless content follows at once (V14), so each visual step started by showing the clock. **Implementation** as in §3.1, §3.2 and §3.4: status `0` raises `IPixelRejectedError` at once, a rejected transfer is sent once more, image windows wait 20 s for their ACK, each window logs its write and ACK times at debug, and a failed background restore or late image is retried after 15 s. 264 tests, 20 of them new, with mutations of the rejection, the transfer retry, the restore retry and its cancellation each caught. **Deploy**: HACS had installed the integration's files as root, from inside the container, so `rsync` couldn't replace them. `deploy.sh` now gives them to the SSH user first. **Real test**: HA restart, with the restore and then the image after startup. Power cut: reconnected in 4 s through the USB adapter, and the GIF came back. Then a reconnection through the ESPHome proxy, back online, with a full restore. Three 58 KB GIFs in 5 windows through the proxy: 24.6–25.0 s each, ACKs 0–48 ms after the writes, no timeout (V17). A rejected command can't come from the UI, because every value the entities offer is valid (V13): C1 is covered by the tests and V13. The retry of a failed restore is covered by the tests only, because a failure can't be caused on demand on the real panel. |

---

## 7. Documentation

- **`CLAUDE.md`**, "What we know about the panel": what V13–V18 find (status `0`, the firmware read, byte 10, the advertisement layout, ACK timings, write sizes). The ACK statuses line changes with C1.
- **`README.md`**: the firmware version and the product id on the device page, discovery by manufacturer data, the new diagnostics fields.
- **`panel-checks.md`**: the outcomes of V13–V18.

---

## 8. Release

- **Version `0.2.0`**: it adds visible behavior (firmware version, product id, a new discovery path) and breaks nothing. A patch version would undersell it (D15).
- Tag `v0.2.0`, published as a GitHub release, installed from HACS on the maintainer's HA, replacing the copy that `deploy.sh` leaves during development.

---

## 9. Risks

| Risk | Effect | Mitigation |
|---|---|---|
| A working command gets status `0` (C1) | It starts failing | V9, V5 and M4 saw only `1` and `3` for valid commands. V13 checks them again. |
| A lost ACK during a transfer | The lock and the player wait up to 20 s per window instead of 8 | Only for transfers; simple commands keep 8 s. V17 sets the value. |
| The firmware read isn't answered | 8 s more on a connection | Asked again only after an HA restart (§3.5) |
| A misread password flag | A spurious warning | Only a warning, never a blocked command (§3.7). V15 checks the unlocked case. |
| The manufacturer matcher matches another product of the vendor | A discovery for something that isn't a panel | The config flow reads the panel info, and an unknown type fails with `cannot_connect` |
| Larger writes through some proxy | Failing transfers | A change only after measuring both paths, with the size derived from the connection (§3.3) |
| `entry.data` written from an advertisement | A config entry write | Only the first time and on a change |

---

## 10. Decisions

Taken on 2026-11-15, when the plan was approved.

| ID | Decision |
|---|---|
| D15 | The release is `v0.2.0`: it adds visible behavior and breaks nothing (§8) |
| D16 | A password-locked panel gets a warning and the flag in the diagnostics, and commands don't fail because of it (§3.7) |
| D17 | The `fa01` matcher stays, next to the name matcher and the new manufacturer data matcher (§3.8) |

Out of scope: C9 and all of text (a later unit), N1–N18 of the comparison, unlocking a panel (N14), a brand table (N17).
