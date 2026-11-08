"""Fixtures for the iPixel Color SE tests."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.syrupy import (
    HomeAssistantSnapshotExtension,
)
from syrupy.assertion import SnapshotAssertion

from custom_components.ipixel_color_se.const import DOMAIN

from .common import ADDRESS, ENTRY_DATA, NAME, FakePanel, service_info

PACKAGE = "custom_components.ipixel_color_se"


@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Use HA's snapshot extension: tests/snapshots and HA's serializer.

    pytest-homeassistant-custom-component and syrupy both define this fixture,
    and which plugin wins depends on the order they are installed in: on
    Linux, syrupy's plain one can win. A conftest fixture always wins.
    """
    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components."""


@pytest.fixture(autouse=True)
def auto_enable_bluetooth(enable_bluetooth: None) -> None:
    """Mock the Bluetooth stack the integration depends on."""


@pytest.fixture
def mock_panel() -> Generator[FakePanel]:
    """Put a simulated panel in range, discovered by HA's Bluetooth.

    Patched where our modules import them, so tests drive advertisements
    and connections through the FakePanel.
    """
    panel = FakePanel()
    with (
        patch(f"{PACKAGE}.connection.establish_connection", panel.establish_connection),
        patch(f"{PACKAGE}.connection.async_ble_device_from_address", panel.ble_device),
        patch(
            f"{PACKAGE}.controller.async_address_present",
            lambda *_args, **_kwargs: panel.present,
        ),
        patch(
            f"{PACKAGE}.controller.async_register_advertisement_callback",
            panel.register_advertisement_callback,
        ),
        patch(f"{PACKAGE}.controller.async_track_unavailable", panel.track_unavailable),
        patch(
            f"{PACKAGE}.config_flow.async_discovered_service_info",
            lambda *_args, **_kwargs: [service_info()] if panel.present else [],
        ),
    ):
        yield panel


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the config entry of a configured display."""
    return MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=ADDRESS, data=ENTRY_DATA
    )


@pytest.fixture
def config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Give HA a config folder of its own, with www and media folders.

    www is served at /local/, media is "My media" in the Media browser. Set
    up the integration after this fixture: media sources read media_dirs then.
    """
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "www").mkdir()
    (tmp_path / "media").mkdir()
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    return tmp_path
