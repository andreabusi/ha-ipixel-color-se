"""Tests for the commands and replies of the panel."""

from datetime import datetime

import pytest

from custom_components.ipixel_color_se import protocol

from .common import INFO_FRAME


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
