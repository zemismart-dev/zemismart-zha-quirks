"""Expose the quirk-owned TS1201 key bank through native HA entities."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import Ts1201Coordinator

PLATFORMS = (
    Platform.TEXT,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.CLIMATE,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the panel; an empty ZHA hub is a valid initial state."""
    coordinator = Ts1201Coordinator(hass, entry)
    entry.runtime_data = coordinator
    try:
        await coordinator.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the panel without disabling a still-current native ZHA quirk."""
    coordinator = entry.runtime_data
    await coordinator.async_begin_unload()
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_abort_unload()
        raise
    if not unloaded:
        await coordinator.async_abort_unload()
        return False
    await coordinator.async_stop()
    return True
