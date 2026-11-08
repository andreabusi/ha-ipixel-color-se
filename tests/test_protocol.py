"""Tests for the commands and replies of the panel."""

from datetime import datetime
from io import BytesIO
import random

from PIL import Image, ImageSequence
import pytest

from custom_components.ipixel_color_se import protocol
from custom_components.ipixel_color_se.state import ImageFit

from .common import INFO_FRAME, gif, noise_gif, still

# An image window: length, type, option, size, CRC, kind, slot, then data
HEADER = 15


def transferred(plan: protocol.SendPlan) -> Image.Image:
    """Return the image a transfer carries, decoded."""
    data = b"".join(window.data[HEADER:] for window in plan.windows)
    return Image.open(BytesIO(data))


@pytest.mark.parametrize(
    ("plan", "data"),
    [
        (protocol.power(True), "05 00 07 01 01"),
        (protocol.power(False), "05 00 07 01 00"),
        (protocol.brightness(1), "05 00 04 80 01"),
        (protocol.brightness(100), "05 00 04 80 64"),
        (protocol.orientation(0), "05 00 06 80 00"),
        (protocol.orientation(3), "05 00 06 80 03"),
    ],
)
def test_simple_commands_wait_for_an_ack(plan: protocol.SendPlan, data: str) -> None:
    """Power, brightness and orientation are acknowledged (check V9)."""
    assert plan.windows == (protocol.Window(data=bytes.fromhex(data), ack=True),)
    assert not plan.final_ack
    assert not plan.response


@pytest.mark.parametrize(
    ("now", "date"),
    [
        # A Sunday: the weekday goes from 1, Monday, to 7
        (datetime(2026, 11, 8, 0, 0, 5), "1a 0b 08 07"),
        # A leap day, on a Tuesday
        (datetime(2028, 2, 29, 12, 0), "1c 02 1d 02"),
        (datetime(2099, 12, 31, 23, 59, 59), "63 0c 1f 04"),
    ],
)
def test_clock_mode_carries_the_date(now: datetime, date: str) -> None:
    """The date goes as DD/MM/YY: the weekday from a two-digit year stays right."""
    plan = protocol.clock_mode(1, True, True, now)

    assert plan.windows == (
        protocol.Window(data=bytes.fromhex(f"0b 00 06 01 01 01 01 {date}"), ack=True),
    )
    assert not plan.final_ack
    assert not plan.response


@pytest.mark.parametrize(
    ("style", "format_24h", "show_date", "options"),
    [
        (1, True, True, "01 01 01"),
        (8, False, False, "08 00 00"),
        (3, False, True, "03 00 01"),
    ],
)
def test_clock_mode_options(
    style: int, format_24h: bool, show_date: bool, options: str
) -> None:
    """Style, 24-hour format and date follow the header, and get an ACK (check V9)."""
    plan = protocol.clock_mode(
        style, format_24h, show_date, datetime(2026, 11, 7, 19, 17)
    )

    assert plan.windows == (
        protocol.Window(
            data=bytes.fromhex(f"0b 00 06 01 {options} 1a 0b 07 06"), ack=True
        ),
    )


def test_set_time_expects_the_info_frame() -> None:
    """set_time carries the given time and waits for a response, not an ACK."""
    plan = protocol.set_time(datetime(2026, 11, 7, 19, 17, 2))

    assert plan.windows == (
        protocol.Window(data=bytes.fromhex("08 00 01 80 13 11 02 00"), ack=False),
    )
    assert plan.response
    assert not plan.final_ack


def test_gif_keeps_its_frames_and_timing() -> None:
    """A GIF is resized to the panel, frame by frame, with its durations (F8.3)."""
    plan = protocol.image(gif(), ImageFit.FILL, 32, 32)

    (window,) = plan.windows
    assert window.ack
    assert plan.final_ack
    assert window.data[:5] == len(window.data).to_bytes(2, "little") + b"\x03\x00\x00"
    assert window.data[5:9] == (len(window.data) - HEADER).to_bytes(4, "little")
    image = transferred(plan)
    assert image.format == "GIF"
    assert image.size == (32, 32)
    assert [frame.info["duration"] for frame in ImageSequence.Iterator(image)] == [
        100,
        200,
        300,
    ]


def test_gif_global_color_table_has_every_color() -> None:
    """The global color table has 256 colors, however few the first frame has.

    The panel stops at a frame whose local table is larger than the global
    one (check V10).
    """
    rng = random.Random(10)  # noqa: S311  # repeatable, not secret
    first = Image.new("RGB", (32, 32), (200, 0, 0))
    noise = Image.frombytes("RGB", (32, 32), rng.randbytes(32 * 32 * 3))
    output = BytesIO()
    first.save(output, format="GIF", save_all=True, append_images=[noise])

    image = transferred(protocol.image(output.getvalue(), ImageFit.FILL, 32, 32))

    assert len(image.global_palette.palette) == 3 * 256
    assert image.convert("RGB").getcolors() == [(32 * 32, (200, 0, 0))]
    image.seek(1)
    assert len(image.convert("RGB").getcolors(maxcolors=32 * 32)) > 128


def test_large_transfers_go_in_windows() -> None:
    """Windows carry 12 KB each: the first has option 0, the others 2."""
    plan = protocol.image(noise_gif(20), ImageFit.FILL, 32, 32)

    assert len(plan.windows) > 2
    assert [window.data[4] for window in plan.windows] == [0] + [2] * (
        len(plan.windows) - 1
    )
    assert all(len(window.data) <= HEADER + 12 * 1024 for window in plan.windows)
    assert all(window.ack for window in plan.windows)
    sizes = {window.data[5:9] for window in plan.windows}
    assert len(sizes) == 1  # every window carries the size of the whole image
    assert transferred(plan).n_frames == 20


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP", "BMP"])
def test_still_images_go_as_png(image_format: str) -> None:
    """Every still format reaches the panel as a PNG, marked as such."""
    plan = protocol.image(still(image_format), ImageFit.FILL, 32, 32)

    (window,) = plan.windows
    assert window.data[2:4] == b"\x02\x00"
    image = transferred(plan)
    assert image.format == "PNG"
    assert image.size == (32, 32)


@pytest.mark.parametrize(
    ("fit", "corner", "center"),
    [
        # Fill crops the sides of a 2:1 image: green everywhere
        (ImageFit.FILL, (0, 255, 0), (0, 255, 0)),
        # Fit shows all of it, with black bars above and below
        (ImageFit.FIT, (0, 0, 0), (0, 255, 0)),
    ],
)
def test_image_fit(
    fit: ImageFit, corner: tuple[int, int, int], center: tuple[int, int, int]
) -> None:
    """Fill crops what's left over, Fit adds black bars (F8.4)."""
    image = transferred(protocol.image(still("PNG", (64, 32)), fit, 32, 32))

    assert image.convert("RGB").getpixel((0, 0)) == corner
    assert image.convert("RGB").getpixel((16, 16)) == center


def test_transparency_becomes_black() -> None:
    """Transparent areas are black on the panel (F8.3)."""
    data = still("PNG", (32, 32), (255, 0, 0, 0), mode="RGBA")

    image = transferred(protocol.image(data, ImageFit.FILL, 32, 32))

    assert image.convert("RGB").getpixel((5, 5)) == (0, 0, 0)


def test_photos_are_turned_upright() -> None:
    """A photo is turned the way its EXIF orientation says, as phones save them."""
    photo = Image.new("RGB", (64, 32), (0, 0, 255))
    photo.paste((255, 0, 0), (0, 0, 32, 32))  # red on the left
    exif = Image.Exif()
    exif[0x0112] = 6  # the camera was turned: show it rotated 90° clockwise
    output = BytesIO()
    photo.save(output, format="JPEG", exif=exif)

    image = transferred(protocol.image(output.getvalue(), ImageFit.FIT, 32, 32))

    # Upright, it's tall: red on top, black bars at the sides
    rgb = image.convert("RGB")
    assert rgb.getpixel((0, 16)) == (0, 0, 0)
    red, _, blue = rgb.getpixel((16, 4))
    assert red > 200
    assert blue < 50


def test_cmyk_jpeg() -> None:
    """A CMYK JPEG, which pypixelcolor can't turn into a PNG, still works."""
    data = still("JPEG", (32, 32), (0, 255, 255, 0), mode="CMYK")

    image = transferred(protocol.image(data, ImageFit.FILL, 32, 32))

    assert image.size == (32, 32)


@pytest.mark.parametrize(
    "data", [b"not an image", gif()[:40], still("PNG")[:60]], ids=["text", "gif", "png"]
)
def test_broken_images(data: bytes) -> None:
    """Data that can't be decoded is an ImageError."""
    with pytest.raises(protocol.ImageError):
        protocol.image(data, ImageFit.FILL, 32, 32)


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (INFO_FRAME, protocol.PanelInfo(device_type=0x81, width=32, height=32)),
        (
            bytes.fromhex("0c 00 01 80 83 00 00 00 00 00 00 ff"),
            protocol.PanelInfo(device_type=0x83, width=64, height=16),
        ),
    ],
)
def test_parse_panel_info(frame: bytes, expected: protocol.PanelInfo) -> None:
    """The type byte gives the resolution."""
    assert protocol.parse_panel_info(frame) == expected


@pytest.mark.parametrize(
    "frame",
    [
        bytes.fromhex("0c 00 01"),  # too short
        bytes.fromhex("05 00 04 80 01"),  # an ACK
        bytes.fromhex("0c 00 01 80 7f 00 00 00 00 00 00 ff"),  # unknown type
    ],
)
def test_parse_panel_info_rejects_other_frames(frame: bytes) -> None:
    """Anything but a known info reply is an error, not a 64×64 default."""
    with pytest.raises(ValueError, match="panel"):
        protocol.parse_panel_info(frame)


@pytest.mark.parametrize(
    ("frame", "status"),
    [
        (bytes.fromhex("05 00 04 80 01"), 1),
        (bytes.fromhex("05 00 02 00 03"), 3),
        (INFO_FRAME, None),
        (bytes.fromhex("05 00"), None),
    ],
)
def test_ack_status(frame: bytes, status: int | None) -> None:
    """ACK frames are 05 00 xx xx <status>."""
    assert protocol.ack_status(frame) == status


def test_ack_status_of_a_command() -> None:
    """Given the command, only an ACK that echoes its bytes 2 and 3 counts (V9)."""
    brightness = protocol.brightness(40).windows[0].data

    assert protocol.ack_status(bytes.fromhex("05 00 04 80 01"), brightness) == 1
    assert protocol.ack_status(bytes.fromhex("05 00 07 01 01"), brightness) is None
