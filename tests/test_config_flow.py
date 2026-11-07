"""Tests for the placeholder config flow."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations

from custom_components.ipixel_color_se.const import DOMAIN


async def test_user_flow_not_yet_available(hass: HomeAssistant) -> None:
    """Starting the flow by hand aborts without creating an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_yet_available"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_abort_reason_is_translated(hass: HomeAssistant) -> None:
    """The abort reason has an English text."""
    translations = await async_get_translations(hass, "en", "config", {DOMAIN})

    assert f"component.{DOMAIN}.config.abort.not_yet_available" in translations
