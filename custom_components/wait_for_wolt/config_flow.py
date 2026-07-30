from __future__ import annotations

import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    WoltApi,
    WoltAuthenticationError,
    WoltConnectionError,
    WoltInvalidPayloadError,
)
from .const import (
    CONF_BEARER_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    DOMAIN,
)

SECRET_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
REQUIRED_SECRET = vol.All(SECRET_SELECTOR, vol.Length(min=1))


async def _async_validate_credentials(hass, data):
    """Validate credentials and retain any tokens rotated during validation."""
    validated = dict(data)
    client_id = validated.get(CONF_CLIENT_ID)
    if not isinstance(client_id, str) or not client_id:
        client_id = str(uuid.uuid4())
        validated[CONF_CLIENT_ID] = client_id

    async def persist_tokens(access_token: str, refresh_token: str) -> None:
        validated[CONF_BEARER_TOKEN] = access_token
        validated[CONF_REFRESH_TOKEN] = refresh_token

    api = WoltApi(
        async_get_clientsession(hass),
        validated.get(CONF_SESSION_ID),
        validated[CONF_BEARER_TOKEN],
        validated[CONF_REFRESH_TOKEN],
        client_id=client_id,
        token_update_callback=persist_tokens,
    )
    await api.fetch_orders()
    return validated


class WoltConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wait for Wolt."""

    VERSION = 1

    DATA_SCHEMA = vol.Schema(
        {
            vol.Optional(CONF_SESSION_ID, default=""): SECRET_SELECTOR,
            vol.Optional(CONF_BEARER_TOKEN, default=""): SECRET_SELECTOR,
            vol.Required(CONF_REFRESH_TOKEN): REQUIRED_SECRET,
            vol.Optional(CONF_VENUE_IDS, default=""): TextSelector({"multiline": True}),
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        }
    )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            user_input[CONF_SESSION_ID] = user_input.get(CONF_SESSION_ID, "")
            venue_ids = [
                v.strip()
                for v in user_input.get(CONF_VENUE_IDS, "").split("\n")
                if v.strip()
            ]
            user_input[CONF_VENUE_IDS] = venue_ids
            try:
                user_input = await _async_validate_credentials(self.hass, user_input)
            except WoltAuthenticationError:
                errors["base"] = "invalid_auth"
            except WoltConnectionError:
                errors["base"] = "cannot_connect"
            except WoltInvalidPayloadError:
                errors["base"] = "invalid_response"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, DEFAULT_NAME), data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=self.DATA_SCHEMA, errors=errors
        )

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
        errors = {}
        if user_input is not None:
            data_updates = {
                CONF_SESSION_ID: user_input.get(CONF_SESSION_ID)
                or entry.data.get(CONF_SESSION_ID, ""),
                CONF_BEARER_TOKEN: user_input[CONF_BEARER_TOKEN],
                CONF_REFRESH_TOKEN: user_input[CONF_REFRESH_TOKEN],
            }
            try:
                data_updates = await _async_validate_credentials(
                    self.hass, data_updates
                )
            except WoltAuthenticationError:
                errors["base"] = "invalid_auth"
            except WoltConnectionError:
                errors["base"] = "cannot_connect"
            except WoltInvalidPayloadError:
                errors["base"] = "invalid_response"
            else:
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
                vol.Optional(CONF_BEARER_TOKEN, default=""): SECRET_SELECTOR,
                vol.Required(CONF_REFRESH_TOKEN): REQUIRED_SECRET,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return WoltOptionsFlowHandler(config_entry)


class WoltOptionsFlowHandler(config_entries.OptionsFlowWithConfigEntry):
    """Handle option flows for the integration."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            venue_ids = [
                v.strip()
                for v in user_input.get(CONF_VENUE_IDS, "").split("\n")
                if v.strip()
            ]

            options = {CONF_VENUE_IDS: venue_ids}
            supplied_access_token = user_input.get(CONF_BEARER_TOKEN, "")
            supplied_refresh_token = user_input.get(CONF_REFRESH_TOKEN, "")
            data = {
                **self.config_entry.data,
                CONF_SESSION_ID: user_input.get(CONF_SESSION_ID, ""),
                CONF_BEARER_TOKEN: (
                    supplied_access_token
                    if supplied_access_token or supplied_refresh_token
                    else self.config_entry.data[CONF_BEARER_TOKEN]
                ),
                CONF_REFRESH_TOKEN: supplied_refresh_token
                or self.config_entry.data[CONF_REFRESH_TOKEN],
            }
            credentials_changed = any(
                user_input.get(key)
                for key in (
                    CONF_BEARER_TOKEN,
                    CONF_REFRESH_TOKEN,
                )
            )
            try:
                if credentials_changed:
                    data = await _async_validate_credentials(self.hass, data)
            except WoltAuthenticationError:
                errors["base"] = "invalid_auth"
            except WoltConnectionError:
                errors["base"] = "cannot_connect"
            except WoltInvalidPayloadError:
                errors["base"] = "invalid_response"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=data,
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
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
