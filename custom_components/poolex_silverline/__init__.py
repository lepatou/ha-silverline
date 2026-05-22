"""The Poolex Silverline integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from pysilverline import SilverlineClient

from .const import CONF_DEVICE_ID, CONF_LOCAL_KEY
from .coordinator import SilverlineConfigEntry, SilverlineCoordinator

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: SilverlineConfigEntry) -> bool:
    """Set up Poolex Silverline from a config entry."""
    client = SilverlineClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        device_id=entry.data[CONF_DEVICE_ID],
        local_key=entry.data[CONF_LOCAL_KEY],
    )
    coordinator = SilverlineCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SilverlineConfigEntry) -> bool:
    """Tear down a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: SilverlineConfigEntry) -> None:
    """Reload on options or data changes."""
    await hass.config_entries.async_reload(entry.entry_id)
