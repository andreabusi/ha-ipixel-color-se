"""Commands and replies of iPixel displays.

The only module that imports pypixelcolor. We use its internal modules, which
may change in any release, so the version is pinned and every import is here.
pypixelcolor only builds the bytes: the transport is ours (connection.py).

Everything here is pure: no Home Assistant, no I/O.
"""

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps
from pypixelcolor.commands.send_image import (
    ResizeMethod as _ResizeMethod,
    _build_send_plan,
    _resize_image,
)
from pypixelcolor.commands.set_brightness import set_brightness as _set_brightness
from pypixelcolor.commands.set_clock_mode import set_clock_mode as _set_clock_mode
from pypixelcolor.commands.set_orientation import set_orientation as _set_orientation
from pypixelcolor.commands.set_power import set_power as _set_power
from pypixelcolor.commands.set_time import set_time as _set_time
from pypixelcolor.lib.device_info import DEVICE_TYPE_MAP, LED_SIZE_MAP
from pypixelcolor.lib.transport.send_plan import SendPlan as _PixelSendPlan

from .state import ImageFit

# ACK status bytes: 0 and 1 acknowledge a window, 3 the end of a transfer
ACK_WINDOW_STATUSES = frozenset({0, 1})
ACK_DONE_STATUS = 3

_PANEL_INFO_COMMAND = b"\x01\x80"

_RESIZE_METHODS = {ImageFit.FILL: _ResizeMethod.CROP, ImageFit.FIT: _ResizeMethod.FIT}
# What Pillow may raise on data it can't decode
_DECODE_ERRORS = (
    OSError,
    ValueError,
    SyntaxError,
    EOFError,
    Image.DecompressionBombError,
)

# A GIF starts with 13 bytes: signature, version and logical screen
# descriptor, whose byte 10 describes the global color table that follows
_GIF_TABLE_FLAGS = 10
_GIF_HEADER = 13
_GIF_COLORS = 256


class ImageError(ValueError):
    """The image can't be decoded or converted for the panel."""


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


def power(on: bool) -> SendPlan:
    """Turn the screen on or off. The panel stays connected either way."""
    return _convert(_set_power(on))


def brightness(level: int) -> SendPlan:
    """Set the brightness, in percent."""
    return _convert(_set_brightness(level))


def orientation(value: int) -> SendPlan:
    """Set the orientation, 0 to 3."""
    return _convert(_set_orientation(value))


def clock_mode(
    style: int, format_24h: bool, show_date: bool, now: datetime
) -> SendPlan:
    """Show the clock in a style, with the date of now.

    pypixelcolor takes styles 0 to 8; the panel shows 1 to 9 (check V5).

    The panel keeps its own time, set by set_time: the command carries only
    the date. pypixelcolor takes it as DD/MM/YY and works out the weekday
    from the two-digit year, which stays right because 2000 years are whole
    Gregorian cycles.
    """
    return _convert(
        _set_clock_mode(
            style=style,
            date=now.strftime("%d/%m/%y"),
            show_date=show_date,
            format_24=format_24h,
        )
    )


def set_time(now: datetime) -> SendPlan:
    """Set the panel's clock to now, which also asks for its info.

    It's the same command as pypixelcolor's get_device_info. The panel
    answers with its info frame, not with an ACK (check V9), so the plan
    expects a response instead.
    """
    return _convert(_set_time(now.hour, now.minute, now.second), response=True)


def image(data: bytes, fit: ImageFit, width: int, height: int) -> SendPlan:
    """Show an image, resized to the panel: a GIF keeps its frames and timing.

    The steps of pypixelcolor's send_image_hex, with a fix for GIFs in
    between: pypixelcolor resizes and converts the image, turning
    transparent areas black. Fill crops what doesn't fit, Fit adds black
    bars. The transfer goes in windows of 12 KB: the panel acknowledges
    each, and the end. CPU-bound: run it in the executor. Raise ImageError
    if the data can't be decoded.
    """
    try:
        data, is_gif = _prepare_image(data)
        data = _resize_image(data, is_gif, width, height, _RESIZE_METHODS[fit])
    except _DECODE_ERRORS as err:
        raise ImageError(f"Can't convert the image: {err}") from err
    if is_gif:
        data = _pad_global_color_table(data)
    return _convert(_build_send_plan(data, is_gif, plan_name="image"))


def _prepare_image(data: bytes) -> tuple[bytes, bool]:
    """Return the data to give pypixelcolor, and whether it's a GIF.

    A GIF goes as it is: pypixelcolor re-encodes its frames. Any other image
    becomes a PNG, the other static format pypixelcolor sends, turned the way
    its EXIF data says, as phone photos need. pypixelcolor's own conversion
    keeps neither the EXIF orientation nor modes like CMYK.
    """
    with Image.open(BytesIO(data)) as img:
        if img.format == "GIF":
            return data, True
        static = ImageOps.exif_transpose(img)
        if static.mode not in {"RGB", "RGBA"}:
            static = static.convert("RGBA")
        output = BytesIO()
        static.save(output, format="PNG")
        return output.getvalue(), False


def _pad_global_color_table(gif: bytes) -> bytes:
    """Give a GIF a global color table of 256 colors (check V10).

    The panel stops at the first frame whose local color table is larger
    than the global one, and shows the frame before it for good. Pillow
    sizes each table to the colors of its frame, so a GIF whose first frame
    had few colors didn't move. The colors added are black and unused: the
    frames don't change.
    """
    flags = gif[_GIF_TABLE_FLAGS]
    colors = 2 << (flags & 0x07) if flags & 0x80 else 0
    end = _GIF_HEADER + 3 * colors
    return (
        gif[:_GIF_TABLE_FLAGS]
        + bytes([flags | 0x87])  # a global table of 2 << 7 colors
        + gif[_GIF_TABLE_FLAGS + 1 : end]
        + bytes(3 * (_GIF_COLORS - colors))
        + gif[end:]
    )


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


def ack_status(frame: bytes, command: bytes | None = None) -> int | None:
    """Return the status of an ACK frame (05 00 xx xx <status>), or None.

    xx xx echoes bytes 2 and 3 of the command that is acknowledged (check
    V9): given the command, an ACK of another one is None too.
    """
    if len(frame) < 5 or frame[0] != 0x05:
        return None
    if command is not None and frame[2:4] != command[2:4]:
        return None
    return frame[4]


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
