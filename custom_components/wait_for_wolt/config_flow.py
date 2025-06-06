from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from .const import (
    DOMAIN,
    CONF_SESSION_ID,
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    DEFAULT_NAME,
)


class WoltConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wait for Wolt."""

    VERSION = 1

    DATA_SCHEMA = vol.Schema(
        {
            vol.Required(CONF_SESSION_ID): str,
            vol.Required(CONF_BEARER_TOKEN): str,
            vol.Required(CONF_REFRESH_TOKEN): str,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        }
    )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(title=user_input.get(CONF_NAME, DEFAULT_NAME), data=user_input)

        return self.async_show_form(step_id="user", data_schema=self.DATA_SCHEMA)

