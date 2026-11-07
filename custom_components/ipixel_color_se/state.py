"""The desired state of a display: what Home Assistant wants it to show.

Saved in one Store per display. Everything here is pure: no Home Assistant.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

BRIGHTNESS_MIN = 1  # 0 gives the same faint light as 1 (check V6)
BRIGHTNESS_MAX = 100
ORIENTATIONS = 4
CLOCK_STYLES = 9


class Mode(StrEnum):
    """What the panel shows."""

    CLOCK = "clock"
    IMAGE = "image"


class ImageFit(StrEnum):
    """How an image is fitted to the panel."""

    FILL = "fill"
    """Fill the screen and crop what's left over."""
    FIT = "fit"
    """Show the whole image, with black bars."""


@dataclass(frozen=True, slots=True)
class ClockSettings:
    """The options of the clock."""

    style: int = 0
    format_24h: bool = True
    show_date: bool = True


@dataclass(frozen=True, slots=True)
class ImageRef:
    """Where the last image came from. The image itself isn't kept."""

    media_id: str
    """As given to play_media, never a signed URL, which expires."""
    title: str | None = None


@dataclass(frozen=True, slots=True)
class DisplayState:
    """What the panel should show. Changed only after the panel accepted it."""

    power: bool = True
    brightness: int | None = None
    """None: never set, so never sent."""
    orientation: int = 0
    mode: Mode | None = None
    """None: unknown, so the content isn't restored."""
    clock: ClockSettings = field(default_factory=ClockSettings)
    image_fit: ImageFit = ImageFit.FILL
    image: ImageRef | None = None
    auto_reconnect: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Return the state as JSON-serializable data, for the Store."""
        return {
            "power": self.power,
            "brightness": self.brightness,
            "orientation": self.orientation,
            "mode": self.mode,
            "clock": {
                "style": self.clock.style,
                "format_24h": self.clock.format_24h,
                "show_date": self.clock.show_date,
            },
            "image_fit": self.image_fit,
            "image": self.image
            and {"media_id": self.image.media_id, "title": self.image.title},
            "auto_reconnect": self.auto_reconnect,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DisplayState:
        """Read a saved state. Missing or invalid values get their default."""
        default = cls()
        clock = data.get("clock")
        clock = clock if isinstance(clock, Mapping) else {}
        return cls(
            power=_bool(data.get("power"), default.power),
            brightness=_int(
                data.get("brightness"), None, BRIGHTNESS_MIN, BRIGHTNESS_MAX
            ),
            orientation=_int(
                data.get("orientation"), default.orientation, 0, ORIENTATIONS - 1
            ),
            mode=_enum(Mode, data.get("mode"), None),
            clock=ClockSettings(
                style=_int(
                    clock.get("style"), default.clock.style, 0, CLOCK_STYLES - 1
                ),
                format_24h=_bool(clock.get("format_24h"), default.clock.format_24h),
                show_date=_bool(clock.get("show_date"), default.clock.show_date),
            ),
            image_fit=_enum(ImageFit, data.get("image_fit"), default.image_fit),
            image=_image(data.get("image")),
            auto_reconnect=_bool(data.get("auto_reconnect"), default.auto_reconnect),
        )


def _bool(value: object, default: bool) -> bool:
    """Return value if it's a bool, else default."""
    return value if isinstance(value, bool) else default


def _int[T: int | None](value: object, default: T, low: int, high: int) -> int | T:
    """Return value if it's an int between low and high, else default."""
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return default


def _enum[E: StrEnum, T](enum: type[E], value: object, default: T) -> E | T:
    """Return value as a member of enum, or default if it isn't one."""
    try:
        return enum(value)
    except ValueError:
        return default


def _image(value: object) -> ImageRef | None:
    """Return a saved image reference, or None if there's no valid one."""
    if not isinstance(value, Mapping) or not isinstance(
        media_id := value.get("media_id"), str
    ):
        return None
    title = value.get("title")
    return ImageRef(media_id=media_id, title=title if isinstance(title, str) else None)
