"""Config and reauth/reconfigure flows for Poolex Silverline."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

from pysilverline import CannotConnect, InvalidAuth, SilverlineClient

from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_LOCAL_KEY): cv.string,
    }
)

_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_LOCAL_KEY): cv.string})


async def _validate(data: Mapping[str, Any]) -> None:
    """Open a connection with the supplied credentials and pull status once.

    Raises CannotConnect or InvalidAuth on failure; returns silently on
    success. Always closes the socket before returning.
    """
    client = SilverlineClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        device_id=data[CONF_DEVICE_ID],
        local_key=data[CONF_LOCAL_KEY],
    )
    try:
        await client.connect()
        await client.get_status()
    finally:
        await client.disconnect()


class SilverlineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the user, reauth, and reconfigure flows."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()
            error = await self._try_validate(user_input)
            if error is None:
                return self.async_create_entry(
                    title=f"Pool Heatpump ({user_input[CONF_HOST]})",
                    data=user_input,
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            candidate = {**entry.data, CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY]}
            error = await self._try_validate(candidate)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY]}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_mismatch(reason="device_id_mismatch")
            error = await self._try_validate(user_input)
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(_USER_SCHEMA, entry.data),
            errors=errors,
        )

    @staticmethod
    async def _try_validate(data: Mapping[str, Any]) -> str | None:
        """Run _validate and translate errors to error keys.

        Returns ``None`` on success, or a translation key on failure.
        """
        try:
            await _validate(data)
        except CannotConnect:
            return "cannot_connect"
        except InvalidAuth:
            return "invalid_auth"
        except ValueError:
            # local_key length / format issue (must be 16 ASCII bytes)
            return "invalid_auth"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during validation")
            return "unknown"
        return None
