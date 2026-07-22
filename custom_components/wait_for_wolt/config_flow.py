from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import TextSelector

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    DOMAIN,
)


class WoltConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wait for Wolt."""

    VERSION = 1

    DATA_SCHEMA = vol.Schema(
        {
            vol.Optional(CONF_SESSION_ID, default=""): str,
            vol.Required(CONF_BEARER_TOKEN): str,
            vol.Required(CONF_REFRESH_TOKEN): str,
            vol.Optional(CONF_VENUE_IDS, default=""): TextSelector({"multiline": True}),
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        }
    )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            user_input[CONF_SESSION_ID] = user_input.get(CONF_SESSION_ID, "")
            venue_ids = [
                v.strip()
                for v in user_input.get(CONF_VENUE_IDS, "").split("\n")
                if v.strip()
            ]
            user_input[CONF_VENUE_IDS] = venue_ids
            return self.async_create_entry(
                title=user_input.get(CONF_NAME, DEFAULT_NAME), data=user_input
            )

        return self.async_show_form(step_id="user", data_schema=self.DATA_SCHEMA)

    async def async_step_import(self, import_data):
        """Import a legacy YAML platform into a durable config entry."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        data = dict(import_data)
        data[CONF_SESSION_ID] = data.get(CONF_SESSION_ID, "")
        venues = data.get(CONF_VENUE_IDS, [])
        if isinstance(venues, str):
            venues = [venue.strip() for venue in venues.split("\n") if venue.strip()]
        data[CONF_VENUE_IDS] = list(venues)
        return self.async_create_entry(
            title=data.get(CONF_NAME, DEFAULT_NAME),
            data=data,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return WoltOptionsFlowHandler(config_entry)


class WoltOptionsFlowHandler(config_entries.OptionsFlowWithConfigEntry):
    """Handle option flows for the integration."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            venue_ids = [
                v.strip()
                for v in user_input.get(CONF_VENUE_IDS, "").split("\n")
                if v.strip()
            ]

            options = {CONF_VENUE_IDS: venue_ids}
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_SESSION_ID: user_input.get(CONF_SESSION_ID, ""),
                    CONF_BEARER_TOKEN: user_input[CONF_BEARER_TOKEN],
                    CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN],
                },
                options=options,
            )
            return self.async_create_entry(
                title="",
                data=options,
            )

        current = "\n".join(
            self.config_entry.options.get(
                CONF_VENUE_IDS, self.config_entry.data.get(CONF_VENUE_IDS, [])
            )
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SESSION_ID,
                    default=self.config_entry.data.get(CONF_SESSION_ID, ""),
                ): str,
                vol.Required(
                    CONF_BEARER_TOKEN,
                    default=self.config_entry.data.get(CONF_BEARER_TOKEN, ""),
                ): str,
                vol.Required(
                    CONF_REFRESH_TOKEN,
                    default=self.config_entry.data.get(CONF_REFRESH_TOKEN, ""),
                ): str,
                vol.Optional(CONF_VENUE_IDS, default=current): TextSelector(
                    {"multiline": True}
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
