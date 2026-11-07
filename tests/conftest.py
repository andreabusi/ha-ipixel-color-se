"""Fixtures for the iPixel Color SE tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipixel_color_se.const import DOMAIN

from .common import ADDRESS, ENTRY_DATA, NAME, FakePanel, service_info

PACKAGE = "custom_components.ipixel_color_se"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components."""


@pytest.fixture(autouse=True)
def auto_enable_bluetooth(enable_bluetooth: None) -> None:
    """Mock the Bluetooth stack the integration depends on."""


@pytest.fixture
def mock_panel() -> Generator[FakePanel]:
    """Put a simulated panel in range, discovered by HA's Bluetooth."""
    panel = FakePanel()
    with (
        patch(f"{PACKAGE}.connection.establish_connection", panel.establish_connection),
        patch(f"{PACKAGE}.connection.async_ble_device_from_address", panel.ble_device),
        patch(
            f"{PACKAGE}.controller.async_address_present",
            lambda *_args, **_kwargs: panel.present,
        ),
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
