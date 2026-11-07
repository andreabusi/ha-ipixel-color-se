"""Commands and replies of iPixel displays.

The only module that imports pypixelcolor. We use its internal modules, which
may change in any release, so the version is pinned and every import is here.
pypixelcolor only builds the bytes: the transport is ours (connection.py).

Everything here is pure: no Home Assistant, no I/O.
"""

from dataclasses import dataclass
from datetime import datetime

from pypixelcolor.commands.set_time import set_time as _set_time
from pypixelcolor.lib.device_info import DEVICE_TYPE_MAP, LED_SIZE_MAP
from pypixelcolor.lib.transport.send_plan import SendPlan as _PixelSendPlan

# ACK status bytes: 0 and 1 acknowledge a window, 3 the end of a transfer
ACK_WINDOW_STATUSES = frozenset({0, 1})
ACK_DONE_STATUS = 3

_PANEL_INFO_COMMAND = b"\x01\x80"


@dataclass(frozen=True, slots=True)
class Window:
    """Bytes the panel acknowledges as a whole."""

    data: bytes
    ack: bool
    """Wait for an ACK after this window."""


@dataclass(frozen=True, slots=True)
class SendPlan:
    """What to write to the panel and what to wait for."""

    name: str
    windows: tuple[Window, ...]
    chunk_size: int = 244
    """Bytes per BLE write."""
    final_ack: bool = False
    """Wait for the end-of-transfer ACK after the last window."""
    response: bool = False
    """The panel answers with a frame that isn't an ACK."""


@dataclass(frozen=True, slots=True)
class PanelInfo:
    """Fixed facts about a panel, from its info reply."""

    device_type: int
    width: int
    height: int


def set_time(now: datetime) -> SendPlan:
    """Set the panel's clock to now, which also asks for its info.

    It's the same command as pypixelcolor's get_device_info. The panel
    answers with its info frame, not with an ACK (check V9), so the plan
    expects a response instead.
    """
    return _convert(_set_time(now.hour, now.minute, now.second), response=True)


def parse_panel_info(frame: bytes) -> PanelInfo:
    """Decode the panel's reply to set_time.

    The reply looks like 0c 00 01 80 <type> …: the type byte selects the
    resolution. Raise ValueError if the frame isn't an info reply or the type
    is unknown; pypixelcolor would silently assume a 64 by 64 panel.
    """
    if len(frame) < 5 or frame[2:4] != _PANEL_INFO_COMMAND:
        raise ValueError(f"Not a panel info frame: {frame.hex(' ')}")
    device_type = frame[4]
    if (led_type := DEVICE_TYPE_MAP.get(device_type)) is None:
        raise ValueError(f"Unknown panel type 0x{device_type:02x}")
    width, height = LED_SIZE_MAP[led_type]
    return PanelInfo(device_type=device_type, width=width, height=height)


def ack_status(frame: bytes) -> int | None:
    """Return the status of an ACK frame (05 00 xx xx <status>), or None.

    xx xx echoes the command that is acknowledged.
    """
    if len(frame) >= 5 and frame[0] == 0x05:
        return frame[4]
    return None


def _convert(plan: _PixelSendPlan, *, response: bool = False) -> SendPlan:
    """Turn a pypixelcolor plan into ours.

    A command answered with a response frame gets no ACK, whatever
    pypixelcolor's policy says.
    """
    ack_per_window = plan.ack_policy.ack_per_window and not response
    return SendPlan(
        name=plan.id,
        windows=tuple(
            Window(data=bytes(window.data), ack=ack_per_window and window.requires_ack)
            for window in plan.windows
        ),
        chunk_size=plan.chunk_size,
        final_ack=plan.ack_policy.ack_final and not response,
        response=response,
    )
