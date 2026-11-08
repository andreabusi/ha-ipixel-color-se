"""Tests for reading images from URLs, /local/ files and media sources."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import aiohttp
from homeassistant.components.media_source import PlayMedia
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from multidict import CIMultiDict, CIMultiDictProxy
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)
import yarl

from custom_components.ipixel_color_se import image_source
from custom_components.ipixel_color_se.const import DOMAIN
from custom_components.ipixel_color_se.image_source import (
    MAX_IMAGE_BYTES,
    ImageData,
    async_resolve,
    redact_url,
)

from .common import gif, still

URL = "https://images.example.com/animals/cat.gif"


@pytest.fixture
async def media_source(hass: HomeAssistant, config_dir: Path) -> None:
    """Set up HA's media sources, with config_dir/media as "My media"."""
    assert await async_setup_component(hass, "media_source", {})


def assert_error(err: pytest.ExceptionInfo, key: str, **placeholders: str) -> None:
    """Check that an error is the translated one for key."""
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == key
    assert placeholders.items() <= err.value.translation_placeholders.items()


# URLs


async def test_url(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """A URL is downloaded; the title is the file name, without the query."""
    data = gif()
    aioclient_mock.get(f"{URL}?token=secret", content=data)

    image = await async_resolve(hass, f"{URL}?token=secret")

    assert image == ImageData(data=data, format="GIF", title="cat.gif")


@pytest.mark.parametrize(
    "response",
    [
        {"status": 404},
        {"exc": aiohttp.ClientConnectionError("Connection refused")},
        {"exc": TimeoutError()},
    ],
    ids=["not found", "refused", "timeout"],
)
async def test_unreachable_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, response: dict
) -> None:
    """A URL that can't be downloaded is image_unavailable, without its query."""
    aioclient_mock.get(URL, **response)

    with pytest.raises(HomeAssistantError) as err:
        await async_resolve(hass, f"{URL}?token=secret")

    assert_error(err, "image_unavailable", source=URL)
    assert not isinstance(err.value, ServiceValidationError)


def _too_many_requests(url: str) -> aiohttp.ClientResponseError:
    """Return the error raise_for_status gives for a 429, as aiohttp has it."""
    request = aiohttp.RequestInfo(
        yarl.URL(url), "GET", CIMultiDictProxy(CIMultiDict()), yarl.URL(url)
    )
    return aiohttp.ClientResponseError(
        request, (), status=429, message="Too Many Requests"
    )


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (_too_many_requests, "429 Too Many Requests"),
        (lambda url: aiohttp.InvalidURL(url, "Bad port"), f"{URL} - Bad port"),
    ],
    ids=["status", "invalid"],
)
async def test_unreachable_url_hides_its_query(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    error: Callable[[str], Exception],
    text: str,
) -> None:
    """The error doesn't show the query, though aiohttp's errors show the URL."""
    aioclient_mock.get(URL, exc=error(f"{URL}?token=secret"))

    with pytest.raises(HomeAssistantError) as err:
        await async_resolve(hass, f"{URL}?token=secret")

    assert_error(err, "image_unavailable", source=URL, error=text)


async def test_large_download_by_its_length(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A file announced over 10 MB isn't downloaded at all (F8.8)."""
    aioclient_mock.get(
        URL, content=b"", headers={"Content-Length": str(MAX_IMAGE_BYTES + 1)}
    )

    with pytest.raises(ServiceValidationError) as err:
        await async_resolve(hass, URL)

    assert_error(err, "image_too_large", source=URL, limit="10")


async def test_large_download_stops(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A download that doesn't announce its length stops past 10 MB."""
    aioclient_mock.get(URL, content=bytes(MAX_IMAGE_BYTES + 1))

    with pytest.raises(ServiceValidationError) as err:
        await async_resolve(hass, URL)

    assert_error(err, "image_too_large")


async def test_ten_megabytes_are_fine(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The limit is inclusive."""
    data = gif()
    aioclient_mock.get(URL, content=data + bytes(MAX_IMAGE_BYTES - len(data)))

    assert (await async_resolve(hass, URL)).format == "GIF"


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"<html>Not found</html>", "html"),
        (still("TIFF"), "tiff"),
    ],
    ids=["html", "tiff"],
)
async def test_unsupported_format(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, data: bytes, name: str
) -> None:
    """The format comes from the bytes: only GIF, PNG, JPEG, WebP and BMP (F8.2)."""
    url = f"https://images.example.com/{name}.gif"
    aioclient_mock.get(url, content=data)

    with pytest.raises(ServiceValidationError) as err:
        await async_resolve(hass, url)

    assert_error(err, "image_unsupported", source=url)


async def test_not_a_url(hass: HomeAssistant) -> None:
    """Something that isn't a URL, a /local/ path or a media source can't be read."""
    with pytest.raises(HomeAssistantError) as err:
        await async_resolve(hass, "cat.gif")

    assert_error(err, "image_unavailable", source="cat.gif")


# /local/ files


@pytest.mark.parametrize("image_format", ["GIF", "PNG", "JPEG", "WEBP", "BMP"])
async def test_local_file(
    hass: HomeAssistant, config_dir: Path, image_format: str
) -> None:
    """/local/ is read from the www folder, without HTTP, whatever its name says."""
    data = still(image_format)
    (config_dir / "www" / "my pictures").mkdir()
    (config_dir / "www" / "my pictures" / "cat.png").write_bytes(data)

    image = await async_resolve(hass, "/local/my%20pictures/cat.png?v=2")

    assert image == ImageData(data=data, format=image_format, title="cat.png")


@pytest.mark.parametrize(
    "media_id",
    ["/local/missing.gif", "/local/../secrets.yaml", "/local/%2e%2e/secrets.yaml"],
)
async def test_local_file_unavailable(
    hass: HomeAssistant, config_dir: Path, media_id: str
) -> None:
    """A missing file is unavailable, and so is anything outside www."""
    (config_dir / "secrets.yaml").write_bytes(still("PNG"))

    with pytest.raises(HomeAssistantError) as err:
        await async_resolve(hass, media_id)

    assert_error(err, "image_unavailable", source=media_id)


async def test_local_file_too_large(hass: HomeAssistant, config_dir: Path) -> None:
    """A file over 10 MB isn't even read."""
    (config_dir / "www" / "huge.gif").write_bytes(bytes(MAX_IMAGE_BYTES + 1))

    with pytest.raises(ServiceValidationError) as err:
        await async_resolve(hass, "/local/huge.gif")

    assert_error(err, "image_too_large", source="/local/huge.gif")


async def test_url_that_isnt_local(
    hass: HomeAssistant, config_dir: Path, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only a relative /local/ path is a local file: another host's is downloaded."""
    data = gif()
    aioclient_mock.get("https://other.example.com/local/cat.gif", content=data)

    image = await async_resolve(hass, "https://other.example.com/local/cat.gif")

    assert image.data == data


# Media sources


@pytest.mark.usefixtures("media_source")
async def test_media_source_file(hass: HomeAssistant, config_dir: Path) -> None:
    """A local media file is read from disk, not through its signed URL."""
    data = gif()
    (config_dir / "media" / "cat.gif").write_bytes(data)

    image = await async_resolve(
        hass, "media-source://media_source/local/cat.gif", "media_player.x"
    )

    assert image == ImageData(data=data, format="GIF", title="cat.gif")


@pytest.mark.usefixtures("media_source")
async def test_media_source_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A media source item that isn't a local file is downloaded from its URL."""
    data = still("PNG")
    aioclient_mock.get("https://photos.example.com/abc?sig=1", content=data)

    with patch.object(
        image_source.media_source,
        "async_resolve_media",
        return_value=PlayMedia("https://photos.example.com/abc?sig=1", "image/png"),
    ) as resolve:
        image = await async_resolve(hass, "media-source://photos/album/sunset.png")

    resolve.assert_called_once_with(
        hass, "media-source://photos/album/sunset.png", None
    )
    assert image == ImageData(data=data, format="PNG", title="sunset.png")


@pytest.mark.usefixtures("media_source")
@pytest.mark.parametrize(
    "media_id",
    [
        "media-source://media_source/local/missing.gif",
        "media-source://not_a_source/cat.gif",
    ],
)
async def test_media_source_unavailable(hass: HomeAssistant, media_id: str) -> None:
    """A deleted file or an unknown source is unavailable (F8.7)."""
    with pytest.raises(HomeAssistantError) as err:
        await async_resolve(hass, media_id)

    assert_error(err, "image_unavailable", source=media_id)


@pytest.mark.parametrize(
    ("url", "redacted"),
    [
        (f"{URL}?token=secret&size=2", f"{URL}?**REDACTED**"),
        (URL, URL),
        ("media-source://media_source/local/cat.gif", None),
    ],
)
def test_redact_url(url: str, redacted: str | None) -> None:
    """Only the query string goes."""
    assert redact_url(url, "**REDACTED**") == (redacted or url)
