"""Single-instance setup for the local TS1201 panel."""

import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class Ts1201ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Allow an empty panel while waiting for a matching ZHA device."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Create the panel without pairing or issuing device commands."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="TS1201 IR Remote", data={})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
