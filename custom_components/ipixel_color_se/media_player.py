"""The image player of iPixel displays."""

from typing import Any

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .controller import IPixelConfigEntry
from .entity import IPixelEntity
from .image_source import MIME_TYPES

PARALLEL_UPDATES = 0

IMAGE_PLAYER = MediaPlayerEntityDescription(
    key="image_player", translation_key="image_player"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IPixelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the image player of a display."""
    async_add_entities([IPixelImagePlayer(entry.runtime_data, IMAGE_PLAYER)])


class IPixelImagePlayer(IPixelEntity, MediaPlayerEntity):
    """Shows GIFs and still images on the panel, which loops a GIF by itself.

    There's nothing to pause. Playing while the image is the content and the
    screen is on, buffering while an image is read or sent, idle otherwise.
    Stop shows the clock.
    """

    _attr_media_content_type = MediaType.IMAGE
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.BROWSE_MEDIA
    )

    @property
    def state(self) -> MediaPlayerState:
        """Return what the player is doing, from the controller (F8.5)."""
        if self.controller.buffering:
            return MediaPlayerState.BUFFERING
        if self.controller.image_shown:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def media_content_id(self) -> str | None:
        """Return the source of the last image, as it was given."""
        image = self.controller.state.image
        return image and image.media_id

    @property
    def media_title(self) -> str | None:
        """Return the file name of the last image."""
        image = self.controller.state.image
        return image and image.title

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Show an image from a URL, a /local/ path or the Media browser.

        The format comes from the image itself, whatever media_type says.
        """
        await self.controller.async_play_media(media_id, self.entity_id)

    async def async_media_play(self) -> None:
        """Show the last image again."""
        await self.controller.async_show_image()

    async def async_media_stop(self) -> None:
        """Show the clock instead of the image (F7.3)."""
        await self.controller.async_show_clock()

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse HA's media for the formats the panel can show (F8.2)."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type in MIME_TYPES,
        )
