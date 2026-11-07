"""Tests for the commands and replies of the panel."""

from datetime import datetime

import pytest

from custom_components.ipixel_color_se import protocol

from .common import INFO_FRAME


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
