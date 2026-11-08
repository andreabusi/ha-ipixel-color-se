"""Tests for the image player."""

from pathlib import Path

from homeassistant.components.media_player import (
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_PLAY_MEDIA,
    MediaPlayerEntityFeature,
)
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID,
    EVENT_STATE_CHANGED,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_STOP,
    SERVICE_TURN_OFF,
    STATE_IDLE,
    STATE_ON,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.ipixel_color_se.image_source import MAX_IMAGE_BYTES

from .common import NAME, FakePanel, gif, still
from .test_init import setup_entry

PLAYER = "media_player.kitchen_pixel_image_player"
MODE = "select.kitchen_pixel_mode"
POWER = "switch.kitchen_pixel_power"
IMAGE_FIT = "select.kitchen_pixel_image_fit"

CAT = "media-source://media_source/local/cat.gif"
PHOTO_URL = "https://images.example.com/photos/beach.jpg?token=secret"


@pytest.fixture
async def player(
    hass: HomeAssistant,
    config_dir: Path,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> list[str]:
    """Set up a display, with a GIF in My media, and record the player's states.

    Only changes of state: attributes may change while it's buffering.
    """
    (config_dir / "media" / "cat.gif").write_bytes(gif())
    await setup_entry(hass, mock_config_entry)
    mock_panel.writes.clear()
    states: list[str] = []

    @callback
    def record(event: Event) -> None:
        if (
            event.data["entity_id"] == PLAYER
            and (state := event.data["new_state"])
            and state.state != (states[-1] if states else STATE_IDLE)
        ):
            states.append(state.state)

    hass.bus.async_listen(EVENT_STATE_CHANGED, record)
    return states


async def play(hass: HomeAssistant, media_id: str, media_type: str = "image") -> None:
    """Call play_media on the player, as the UI and automations do."""
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_PLAY_MEDIA,
        {
            ATTR_ENTITY_ID: PLAYER,
            ATTR_MEDIA_CONTENT_ID: media_id,
            ATTR_MEDIA_CONTENT_TYPE: media_type,
        },
        blocking=True,
    )


async def call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    """Call an entity action and wait for it."""
    await hass.services.async_call(domain, service, data, blocking=True)


async def test_player(hass: HomeAssistant, player: list[str]) -> None:
    """The player is idle until it plays, and can browse, play and stop."""
    state = hass.states.get(PLAYER)

    assert state.state == STATE_IDLE
    assert state.attributes["friendly_name"] == f"{NAME} Image player"
    assert state.attributes["supported_features"] == (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.BROWSE_MEDIA
    )


async def test_play_from_the_media_browser(
    hass: HomeAssistant, player: list[str], mock_panel: FakePanel
) -> None:
    """A GIF from My media goes through buffering to playing (F8.5)."""
    await play(hass, CAT, "image/gif")

    assert player == ["buffering", "playing"]
    state = hass.states.get(PLAYER)
    assert state.attributes["media_title"] == "cat.gif"
    assert state.attributes["media_content_id"] == CAT
    assert state.attributes["media_content_type"] == "image"
    assert hass.states.get(MODE).state == "image"
    assert mock_panel.commands == ["gif"]
    assert mock_panel.shown.size == (32, 32)
    assert mock_panel.shown.n_frames == 3


async def test_play_a_photo_from_a_url(
    hass: HomeAssistant,
    player: list[str],
    mock_panel: FakePanel,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """With Fit the photo is whole, with black bars; Fill sends it again cropped."""
    aioclient_mock.get(PHOTO_URL, content=still("JPEG", (64, 32), (0, 0, 255)))
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: IMAGE_FIT, ATTR_OPTION: "fit"},
    )

    await play(hass, PHOTO_URL)

    assert hass.states.get(PLAYER).attributes["media_title"] == "beach.jpg"
    assert mock_panel.shown.convert("RGB").getpixel((0, 0)) == (0, 0, 0)

    mock_panel.writes.clear()
    await call(
        hass,
        "select",
        SERVICE_SELECT_OPTION,
        **{ATTR_ENTITY_ID: IMAGE_FIT, ATTR_OPTION: "fill"},
    )

    assert mock_panel.commands == ["png"]
    _, _, blue = mock_panel.shown.convert("RGB").getpixel((0, 0))
    assert blue > 200
    assert aioclient_mock.call_count == 2  # read again from its source (F8.7)


async def test_play_a_local_file(
    hass: HomeAssistant, player: list[str], config_dir: Path, mock_panel: FakePanel
) -> None:
    """A file in www plays from /local/."""
    (config_dir / "www" / "logo.png").write_bytes(still("PNG"))

    await play(hass, "/local/logo.png")

    assert hass.states.get(PLAYER).state == STATE_PLAYING
    assert hass.states.get(PLAYER).attributes["media_title"] == "logo.png"
    assert mock_panel.commands == ["png"]


async def test_play_turns_the_screen_on(
    hass: HomeAssistant, player: list[str], mock_panel: FakePanel
) -> None:
    """With the screen off, playing an image turns Power back on (F5.3)."""
    await call(hass, "switch", SERVICE_TURN_OFF, **{ATTR_ENTITY_ID: POWER})
    assert hass.states.get(PLAYER).state == STATE_IDLE

    await play(hass, CAT)

    assert hass.states.get(POWER).state == STATE_ON
    assert hass.states.get(PLAYER).state == STATE_PLAYING
    assert mock_panel.screen_on


async def test_stop_and_play(
    hass: HomeAssistant, player: list[str], mock_panel: FakePanel
) -> None:
    """Stop shows the clock; Play shows the last image again (F8.6)."""
    await play(hass, CAT)
    mock_panel.writes.clear()

    await call(hass, MEDIA_PLAYER_DOMAIN, SERVICE_MEDIA_STOP, entity_id=PLAYER)

    assert mock_panel.commands == ["clock 1 24h date", "set_time"]
    assert hass.states.get(MODE).state == "clock"
    assert hass.states.get(PLAYER).state == STATE_IDLE
    # Still the last image, for Play
    assert hass.states.get(PLAYER).attributes["media_title"] == "cat.gif"

    mock_panel.writes.clear()
    await call(hass, MEDIA_PLAYER_DOMAIN, SERVICE_MEDIA_PLAY, entity_id=PLAYER)

    assert mock_panel.commands == ["gif"]
    assert hass.states.get(MODE).state == "image"
    assert hass.states.get(PLAYER).state == STATE_PLAYING


async def test_play_without_an_image(hass: HomeAssistant, player: list[str]) -> None:
    """Play with nothing played yet asks to play something first (F7.2)."""
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, MEDIA_PLAYER_DOMAIN, SERVICE_MEDIA_PLAY, entity_id=PLAYER)

    assert str(err.value) == (
        f"{NAME} has no image to show yet. Play one with the image player first"
    )


@pytest.mark.parametrize(
    ("media_id", "error", "message"),
    [
        (
            "/local/huge.gif",
            ServiceValidationError,
            "The image /local/huge.gif is larger than 10 MB",
        ),
        (
            "/local/notes.gif",
            ServiceValidationError,
            "/local/notes.gif isn't an image the display can show. Use a GIF, PNG, "
            "JPEG, WebP or BMP file",
        ),
        (
            "https://images.example.com/gone.gif?token=secret",
            HomeAssistantError,
            "Can't read the image https://images.example.com/gone.gif: ",
        ),
        (
            "media-source://media_source/local/deleted.gif",
            HomeAssistantError,
            "Can't read the image media-source://media_source/local/deleted.gif: ",
        ),
    ],
    ids=["too large", "unsupported", "unreachable", "deleted"],
)
async def test_errors_are_visible(
    hass: HomeAssistant,
    player: list[str],
    config_dir: Path,
    mock_panel: FakePanel,
    aioclient_mock: AiohttpClientMocker,
    media_id: str,
    error: type[Exception],
    message: str,
) -> None:
    """A file over 10 MB, an unknown format or a missing source fail visibly (F8.8)."""
    (config_dir / "www" / "huge.gif").write_bytes(bytes(MAX_IMAGE_BYTES + 1))
    (config_dir / "www" / "notes.gif").write_text("Not a GIF")
    aioclient_mock.get("https://images.example.com/gone.gif", status=404)

    with pytest.raises(error) as err:
        await play(hass, media_id)

    assert str(err.value).startswith(message)
    assert "secret" not in str(err.value)
    assert player == ["buffering", "idle"]
    assert hass.states.get(MODE).state != "image"
    assert mock_panel.writes == []


async def test_failed_play_keeps_the_last_image(
    hass: HomeAssistant, player: list[str], mock_panel: FakePanel
) -> None:
    """After a failed play, the player is back to the image it had."""
    await play(hass, CAT)

    with pytest.raises(HomeAssistantError):
        await play(hass, "/local/missing.gif")

    assert player == ["buffering", "playing", "buffering", "playing"]
    assert hass.states.get(PLAYER).attributes["media_content_id"] == CAT


async def test_browse_media(
    hass: HomeAssistant,
    player: list[str],
    config_dir: Path,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """The Media browser shows folders and the images the panel can show (F8.2)."""
    media = config_dir / "media"
    for name in ("photo.jpg", "logo.png", "art.webp", "old.bmp", "notes.txt"):
        (media / name).write_bytes(b"")
    (media / "clip.mp4").write_bytes(b"")
    (media / "holidays").mkdir()
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "media_player/browse_media",
            "entity_id": PLAYER,
            "media_content_type": "image",
            "media_content_id": "media-source://media_source/local/.",
        }
    )
    response = await client.receive_json()

    assert response["success"]
    assert sorted(child["title"] for child in response["result"]["children"]) == [
        "art.webp",
        "cat.gif",
        "holidays",
        "logo.png",
        "old.bmp",
        "photo.jpg",
    ]
    # The video; HA doesn't list the text file at all
    assert response["result"]["not_shown"] == 1


async def test_unavailable_without_the_panel(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """The player is a control: it needs the panel in range (T1)."""
    mock_panel.present = False

    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(PLAYER).state == STATE_UNAVAILABLE
