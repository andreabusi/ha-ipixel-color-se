"""Where images come from: URLs, /local/ files and media sources.

Turns the media_id given to play_media into the image's bytes, format and
title. The image is never kept: the controller keeps the media_id, and comes
back here whenever it shows the image again (F8.7).
"""

from dataclasses import dataclass
from io import BytesIO
import logging
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import aiohttp
from homeassistant.components import media_source
from homeassistant.components.media_player import async_process_play_media_url
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from PIL import Image, UnidentifiedImageError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The source can be much larger than what the panel gets: a GIF is shrunk
# to the panel before it's sent
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DOWNLOAD_TIMEOUT = 30.0
_DOWNLOAD_CHUNK = 64 * 1024

LOCAL_PREFIX = "/local/"

# The formats pypixelcolor handles (F8.2), by Pillow's name, with their MIME
# types for the Media browser. Older Pythons name BMP image/x-ms-bmp.
FORMATS = {
    "GIF": ("image/gif",),
    "PNG": ("image/png",),
    "JPEG": ("image/jpeg",),
    "WEBP": ("image/webp",),
    "BMP": ("image/bmp", "image/x-ms-bmp"),
}
MIME_TYPES = frozenset(mime for mimes in FORMATS.values() for mime in mimes)


@dataclass(frozen=True, slots=True)
class ImageData:
    """An image, as read from its source."""

    data: bytes
    format: str
    """Pillow's name of the format, a key of FORMATS."""
    title: str
    """The file name."""


async def async_resolve(
    hass: HomeAssistant, media_id: str, entity_id: str | None = None
) -> ImageData:
    """Read the image a media_id points to.

    A media source item is read from disk when it's a local file, else
    downloaded from the URL it resolves to; entity_id is the player that
    asked, if any. A /local/ path is read from the www folder, without HTTP,
    so it works while HA starts. Anything else is downloaded through HA's
    HTTP session, which also signs HA's own relative URLs.

    Raise image_unavailable if it can't be read, image_too_large over 10 MB
    and image_unsupported if it isn't a GIF, PNG, JPEG, WebP or BMP.
    """
    source = redact_url(media_id, "")
    if media_source.is_media_source_id(media_id):
        try:
            item = await media_source.async_resolve_media(hass, media_id, entity_id)
        except media_source.MediaSourceError as err:
            raise _unavailable(source, err) from err
        if item.path is not None:
            title = item.path.name
            data = await _async_read(hass, item.path, source)
        else:
            title = _file_name(media_id)
            data = await _async_download(hass, item.url, source)
    elif media_id.startswith(LOCAL_PREFIX):
        path = _local_path(hass, media_id)
        title = path.name
        data = await _async_read(hass, path, source, root=_www(hass))
    else:
        title = _file_name(media_id)
        data = await _async_download(hass, media_id, source)

    image_format = await hass.async_add_executor_job(_detect_format, data)
    if image_format not in FORMATS:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="image_unsupported",
            translation_placeholders={"source": source},
        )
    _LOGGER.debug("Read %s: %s, %d bytes", source, image_format, len(data))
    return ImageData(data=data, format=image_format, title=title)


def redact_url(url: str, replacement: str) -> str:
    """Return url with its query string, which may hold a token, replaced."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    return parts._replace(query=replacement).geturl().removesuffix("?")


def _file_name(media_id: str) -> str:
    """Return the last part of a URL's path, or the URL if it has none."""
    path = unquote(urlsplit(media_id).path)
    return PurePosixPath(path).name or redact_url(media_id, "")


def _www(hass: HomeAssistant) -> Path:
    """Return the folder HA serves at /local/."""
    return Path(hass.config.path("www"))


def _local_path(hass: HomeAssistant, media_id: str) -> Path:
    """Return the file a /local/ URL names, in the www folder."""
    relative = unquote(urlsplit(media_id).path).removeprefix(LOCAL_PREFIX)
    return _www(hass) / relative


async def _async_read(
    hass: HomeAssistant, path: Path, source: str, *, root: Path | None = None
) -> bytes:
    """Read a file, at most MAX_IMAGE_BYTES, and only inside root if given."""

    def read() -> bytes | None:
        """Return the file's bytes, or None if it's too large."""
        resolved = path.resolve()
        if root is not None and not resolved.is_relative_to(root.resolve()):
            raise FileNotFoundError(f"{path} isn't in {root}")
        if resolved.stat().st_size > MAX_IMAGE_BYTES:
            return None
        return resolved.read_bytes()

    try:
        data = await hass.async_add_executor_job(read)
    except OSError as err:
        raise _unavailable(source, err) from err
    if data is None:
        raise _too_large(source)
    return data


async def _async_download(hass: HomeAssistant, url: str, source: str) -> bytes:
    """Download a URL, stopping as soon as it's over MAX_IMAGE_BYTES."""
    try:
        url = async_process_play_media_url(hass, url)
    except HomeAssistantError as err:
        # A relative URL, and HA doesn't know its own
        raise _unavailable(source, err) from err
    session = async_get_clientsession(hass)
    data = bytearray()
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
        ) as response:
            response.raise_for_status()
            length = response.headers.get(aiohttp.hdrs.CONTENT_LENGTH, "")
            if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
                raise _too_large(source)
            async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK):
                data += chunk
                if len(data) > MAX_IMAGE_BYTES:
                    raise _too_large(source)
    except aiohttp.ClientResponseError as err:
        # Its text ends with the URL, query and all, maybe after redirects
        raise _unavailable(source, f"{err.status} {err.message}") from err
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        # ValueError: not a URL aiohttp can fetch. An invalid URL's text is
        # the URL itself.
        raise _unavailable(
            source, (str(err) or repr(err)).replace(url, source)
        ) from err
    return bytes(data)


def _detect_format(data: bytes) -> str | None:
    """Return Pillow's name of the image's format, or None if it isn't one.

    Pillow reads only the header here. Runs in the executor.
    """
    try:
        with Image.open(BytesIO(data)) as img:
            return img.format
    except UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError:
        return None


def _unavailable(source: str, err: Exception | str) -> HomeAssistantError:
    """Return the error for an image that can't be read.

    The error's text must not hold a URL's query, which may carry a token.
    """
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="image_unavailable",
        translation_placeholders={"source": source, "error": str(err) or repr(err)},
    )


def _too_large(source: str) -> ServiceValidationError:
    """Return the error for an image over MAX_IMAGE_BYTES."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="image_too_large",
        translation_placeholders={
            "source": source,
            "limit": str(MAX_IMAGE_BYTES // (1024 * 1024)),
        },
    )
