"""Tests for the diagnostics download."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion

from .common import FakePanel, service_info
from .test_init import setup_entry


@pytest.mark.freeze_time("2026-11-07 18:17:00+00:00")
async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Diagnostics describe the entry, the connection and the advertisements."""
    await setup_entry(hass, mock_config_entry)

    with patch(
        "custom_components.ipixel_color_se.diagnostics.async_last_service_info",
        return_value=service_info(),
    ):
        diagnostics = await get_diagnostics_for_config_entry(
            hass, hass_client, mock_config_entry
        )

    assert diagnostics == snapshot
