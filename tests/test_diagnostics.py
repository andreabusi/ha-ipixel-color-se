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

from custom_components.ipixel_color_se.state import DisplayState, ImageRef, Mode

from .common import FakePanel, service_info
from .test_controller import save_state
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


async def test_diagnostics_hide_tokens_in_urls(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    hass_storage: dict,
    mock_panel: FakePanel,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The query string of the image's URL, which may hold a token, is redacted."""
    mock_panel.present = False
    save_state(
        hass_storage,
        mock_config_entry,
        DisplayState(
            mode=Mode.IMAGE,
            image=ImageRef(
                media_id="https://images.example.com/cat.gif?token=secret",
                title="cat.gif",
            ),
        ),
    )
    await setup_entry(hass, mock_config_entry)

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert diagnostics["state"]["image"] == {
        "media_id": "https://images.example.com/cat.gif?**REDACTED**",
        "title": "cat.gif",
    }
