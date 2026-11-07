"""Tests for the desired state and how it's saved."""

import json

import pytest

from custom_components.ipixel_color_se.state import (
    ClockSettings,
    DisplayState,
    ImageFit,
    ImageRef,
    Mode,
)


def test_defaults() -> None:
    """A new display changes nothing on the panel until asked (plan §3)."""
    state = DisplayState()

    assert state.power
    assert state.brightness is None
    assert state.orientation == 0
    assert state.mode is None
    assert state.clock == ClockSettings(style=0, format_24h=True, show_date=True)
    assert state.image_fit is ImageFit.FILL
    assert state.image is None
    assert state.auto_reconnect


def test_round_trip() -> None:
    """Every field survives saving to JSON and reading back."""
    state = DisplayState(
        power=False,
        brightness=40,
        orientation=2,
        mode=Mode.IMAGE,
        clock=ClockSettings(style=8, format_24h=False, show_date=False),
        image_fit=ImageFit.FIT,
        image=ImageRef(
            media_id="media-source://media_source/local/cat.gif", title="cat.gif"
        ),
        auto_reconnect=False,
    )

    data = json.loads(json.dumps(state.as_dict()))

    assert data["mode"] == "image"
    assert data["image"] == {
        "media_id": "media-source://media_source/local/cat.gif",
        "title": "cat.gif",
    }
    assert DisplayState.from_dict(data) == state


def test_missing_values_get_their_default() -> None:
    """Data saved by an older version, without some keys, still loads."""
    assert DisplayState.from_dict({}) == DisplayState()
    assert DisplayState.from_dict({"power": False}) == DisplayState(power=False)


@pytest.mark.parametrize(
    "data",
    [
        {"power": "off"},
        {"brightness": 0},
        {"brightness": 101},
        {"brightness": True},
        {"brightness": "40"},
        {"orientation": 4},
        {"orientation": -1},
        {"mode": "text"},
        {"clock": {"style": 9}},
        {"clock": "style_1"},
        {"image_fit": "stretch"},
        {"image": {"title": "no media_id"}},
        {"image": "cat.gif"},
        {"auto_reconnect": None},
    ],
)
def test_invalid_values_get_their_default(data: dict) -> None:
    """A damaged file doesn't break the setup."""
    assert DisplayState.from_dict(data) == DisplayState()
