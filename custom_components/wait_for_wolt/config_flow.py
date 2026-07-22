from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    DOMAIN,
)

SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
REQUIRED_SECRET = vol.All(SECRET_SELECTOR, vol.Length(min=1))


class WoltConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wait for Wolt."""

    VERSION = 1

    DATA_SCHEMA = vol.Schema(
        {
            vol.Optional(CONF_SESSION_ID, default=""): SECRET_SELECTOR,
            vol.Required(CONF_BEARER_TOKEN): REQUIRED_SECRET,
            vol.Required(CONF_REFRESH_TOKEN): REQUIRED_SECRET,
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

    async def async_step_reauth(self, entry_data):
        """Start reauthentication after the coordinator rejects credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Replace rejected credentials and reload the config entry."""
        entry = self._get_reauth_entry()
        if user_input is not None:
            data_updates = {
                CONF_SESSION_ID: user_input.get(CONF_SESSION_ID)
                or entry.data.get(CONF_SESSION_ID, ""),
                CONF_BEARER_TOKEN: user_input[CONF_BEARER_TOKEN],
                CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN],
            }
            if entry.state is ConfigEntryState.LOADED:
                # The loaded entry's update listener owns the one required
                # reload. Scheduling another here causes duplicate Wolt polls.
                return self.async_update_and_abort(
                    entry,
                    data_updates=data_updates,
                )
            # First-refresh reauth has no update listener yet, so the flow must
            # explicitly schedule setup with the replacement credentials.
            return self.async_update_reload_and_abort(
                entry,
                data_updates=data_updates,
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_SESSION_ID, default=""): SECRET_SELECTOR,
                vol.Required(CONF_BEARER_TOKEN): REQUIRED_SECRET,
                vol.Required(CONF_REFRESH_TOKEN): REQUIRED_SECRET,
            }
        )
        return self.async_show_form(step_id="reauth_confirm", data_schema=schema)

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
                    CONF_BEARER_TOKEN: user_input.get(CONF_BEARER_TOKEN)
                    or self.config_entry.data[CONF_BEARER_TOKEN],
                    CONF_REFRESH_TOKEN: user_input.get(CONF_REFRESH_TOKEN)
                    or self.config_entry.data[CONF_REFRESH_TOKEN],
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
                    default="",
                ): SECRET_SELECTOR,
                vol.Optional(CONF_BEARER_TOKEN, default=""): SECRET_SELECTOR,
                vol.Optional(CONF_REFRESH_TOKEN, default=""): SECRET_SELECTOR,
                vol.Optional(CONF_VENUE_IDS, default=current): TextSelector(
                    {"multiline": True}
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
