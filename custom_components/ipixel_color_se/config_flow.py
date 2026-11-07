"""Config flow for the iPixel Color SE integration."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class IPixelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iPixel Color SE.

    Placeholder: discovery and setup arrive in a later milestone.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow started by the user."""
        return self.async_abort(reason="not_yet_available")
