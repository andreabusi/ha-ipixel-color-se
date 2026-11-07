"""Tests for the config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from bleak.exc import BleakError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ipixel_color_se.config_flow import MANUAL_ENTRY
from custom_components.ipixel_color_se.const import DOMAIN

from .common import ADDRESS, BLE_NAME, ENTRY_DATA, NAME, FakePanel, service_info

PACKAGE = "custom_components.ipixel_color_se"


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep the created entries from loading: these tests are about the flow."""
    with patch(f"{PACKAGE}.async_setup_entry", return_value=True) as mock:
        yield mock


async def test_bluetooth_discovery(hass: HomeAssistant, mock_panel: FakePanel) -> None:
    """A discovered panel is confirmed with a name and gets its resolution."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {
        "ble_name": BLE_NAME,
        "address": ADDRESS,
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: f"  {NAME} "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == ADDRESS
    # The flow's own connection is closed, freeing the panel for the entry
    assert len(mock_panel.clients) == 1
    assert not mock_panel.connected


async def test_bluetooth_discovery_proposes_the_ble_name(
    hass: HomeAssistant, mock_panel: FakePanel
) -> None:
    """The name field defaults to the Bluetooth name, used if left blank."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    schema = result["data_schema"].schema
    assert next(iter(schema)).default() == BLE_NAME

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: " "}
    )
    assert result["title"] == BLE_NAME


async def test_bluetooth_discovery_already_configured(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A panel that is set up already isn't proposed again."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"connect_error": BleakError("out of range")}, "cannot_connect"),
        ({"present": False}, "cannot_connect"),
        ({"responder": lambda _data: []}, "cannot_connect"),
        (
            {"info_frame": bytes.fromhex("0c 00 01 80 7f 00 00 00 00 00 00 ff")},
            "unsupported_panel",
        ),
    ],
)
async def test_confirm_errors_can_be_retried(
    hass: HomeAssistant,
    mock_panel: FakePanel,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, object],
    error: str,
) -> None:
    """A failed check shows the form again with the error, then succeeds."""
    monkeypatch.setattr(f"{PACKAGE}.connection.RESPONSE_TIMEOUT", 0.01)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    saved = {name: getattr(mock_panel, name) for name in change}
    for name, value in change.items():
        setattr(mock_panel, name, value)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    assert not mock_panel.connected

    for name, value in saved.items():
        setattr(mock_panel, name, value)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_confirm_unexpected_error(
    hass: HomeAssistant, mock_panel: FakePanel
) -> None:
    """An unexpected exception shows the unknown error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    with patch(
        f"{PACKAGE}.config_flow.async_read_panel_info", side_effect=RuntimeError
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: NAME}
        )

    assert result["errors"] == {"base": "unknown"}


async def test_info_request_uses_ha_time_zone(
    hass: HomeAssistant, mock_panel: FakePanel, freezer: FrozenDateTimeFactory
) -> None:
    """The panel's clock is set to HA's local time, not the system's."""
    await hass.config.async_set_time_zone("Europe/Rome")
    freezer.move_to("2026-11-07 18:17:02+00:00")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )

    await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NAME: NAME})

    assert mock_panel.writes == [bytes.fromhex("08 00 01 80 13 11 02 00")]


async def test_user_lists_only_new_ipixel_panels(
    hass: HomeAssistant, mock_panel: FakePanel
) -> None:
    """Other devices and configured panels are left out of the list."""
    MockConfigEntry(
        domain=DOMAIN, unique_id="11:22:33:44:55:66", data=ENTRY_DATA
    ).add_to_hass(hass)
    discovered = [
        service_info(),
        service_info(address="11:22:33:44:55:66", name="LED_BLE_33445566"),
        service_info(address="22:33:44:55:66:77", name="Keyboard"),
        service_info(
            address="33:44:55:66:77:88",
            name="Panel",
            service_uuids=["0000fa01-0000-1000-8000-00805f9b34fb"],
        ),
    ]
    with patch(
        f"{PACKAGE}.config_flow.async_discovered_service_info", return_value=discovered
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    selector = result["data_schema"].schema[CONF_ADDRESS]
    assert [option["value"] for option in selector.config["options"]] == [
        "33:44:55:66:77:88",
        ADDRESS,
        MANUAL_ENTRY,
    ]


async def test_user_picks_a_panel(hass: HomeAssistant, mock_panel: FakePanel) -> None:
    """Picking a panel from the list leads to the name step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["step_id"] == "bluetooth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: NAME}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA


async def test_user_without_panels_goes_to_manual(
    hass: HomeAssistant, mock_panel: FakePanel
) -> None:
    """With nothing in range, the flow asks for the address directly."""
    mock_panel.present = False

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["step_id"] == "manual"


async def test_manual_entry(hass: HomeAssistant, mock_panel: FakePanel) -> None:
    """The manual entry checks and normalizes the address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: MANUAL_ENTRY}
    )
    assert result["step_id"] == "manual"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "not an address", CONF_NAME: NAME}
    )
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: " aa-bb-cc-dd-ee-ff ", CONF_NAME: NAME}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["result"].unique_id == ADDRESS


async def test_manual_entry_already_configured(
    hass: HomeAssistant, mock_panel: FakePanel, mock_config_entry: MockConfigEntry
) -> None:
    """A configured address can't be added by hand either."""
    mock_config_entry.add_to_hass(hass)
    mock_panel.present = False
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS, CONF_NAME: NAME}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_flow_strings_are_translated(hass: HomeAssistant) -> None:
    """Every error and abort reason the flow uses has an English text."""
    translations = await async_get_translations(hass, "en", "config", {DOMAIN})
    keys = [
        "error.cannot_connect",
        "error.invalid_address",
        "error.unsupported_panel",
        "error.unknown",
        "abort.already_configured",
        "abort.already_in_progress",
    ]

    for key in keys:
        assert f"component.{DOMAIN}.config.{key}" in translations
