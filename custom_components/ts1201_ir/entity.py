"""Entity identity and dynamic platform membership for the quirk-owned bank."""

from __future__ import annotations

import asyncio
import inspect

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import (
    EntityPlatform,
    async_get_current_platform,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class Ts1201Entity(CoordinatorEntity):
    """An entity always bound through the coordinator, never to a cached cluster."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, ieee, suffix, name):
        super().__init__(coordinator)
        self.ieee = ieee
        self.key_id = None
        self._attr_unique_id = f"{ieee}_{suffix}"
        self._attr_name = name
        self._manager = None

    @property
    def device_info(self):
        """Use a regular companion child device; never merge config-entry scopes."""
        info = dr.DeviceInfo(
            identifiers={(DOMAIN, self.ieee)},
            name="TS1201 红外遥控器",
            manufacturer="Zemismart",
            model="TS1201",
        )
        if parent_id := self.coordinator.parent_device_id(self.ieee):
            info["via_device_id"] = parent_id
        return info

    @property
    def snapshot(self):
        return self.coordinator.snapshot(self.ieee)

    @property
    def available(self):
        return self.coordinator.is_available(self.ieee, self.key_id)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._manager and self._manager.entities.get(self.unique_id) is not self:
            self.hass.async_create_task(self.async_remove(force_remove=True))

    @callback
    def _handle_coordinator_update(self):
        # A coordinator notification may already contain the callback of an
        # entity removed by this same update. Do not write a disabled entity;
        # enabled but offline entities still need their unavailable state.
        if self.enabled:
            super()._handle_coordinator_update()

    async def async_action(self, action, value=None):
        await self.coordinator.async_key_action(self.ieee, action, value)


class DynamicEntities:
    """Keep IDs and user registry preferences when a key is deleted and restored."""

    def __init__(
        self, hass, coordinator, add_entities, factory, managed_ids, platform_domain
    ):
        self.hass = hass
        self.coordinator = coordinator
        self.add_entities = add_entities
        self.factory = factory
        self.managed_ids = managed_ids
        self.platform_domain = platform_domain
        self.entities = {}
        self._closed = False
        self._paused = False
        self._dirty = False
        self._task = None
        self._unsub = coordinator.async_add_listener(self._schedule)
        coordinator.managers.append(self)

    def _schedule(self):
        self._dirty = True
        if (
            not self._closed
            and not self._paused
            and (self._task is None or self._task.done())
        ):
            self._task = self.hass.async_create_task(
                self.async_sync(), f"{DOMAIN} entity sync"
            )

    def _soft_delete(self, entity):
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity.entity_id) if entity.entity_id else None
        self._soft_delete_entry(entry)

    def _soft_delete_entry(self, entry):
        registry = er.async_get(self.hass)
        if entry and entry.disabled_by is None:
            options = {
                **entry.options.get(DOMAIN, {}),
                "disabled_for_removed_key": True,
            }
            registry.async_update_entity_options(entry.entity_id, DOMAIN, options)
            registry.async_update_entity(
                entry.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )

    def _restore_registry(self, entity):
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            entity.PLATFORM, DOMAIN, entity.unique_id
        )
        entry = registry.async_get(entity_id) if entity_id else None
        if not entry or not entry.options.get(DOMAIN, {}).get(
            "disabled_for_removed_key"
        ):
            return
        if entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
            registry.async_update_entity(entry.entity_id, disabled_by=None)
        options = dict(entry.options.get(DOMAIN, {}))
        options.pop("disabled_for_removed_key", None)
        registry.async_update_entity_options(entry.entity_id, DOMAIN, options)

    async def async_sync(self):
        self._dirty = True
        while self._dirty and not self._closed and not self._paused:
            self._dirty = False
            wanted = {
                entity.unique_id: entity for entity in self.factory(self.coordinator)
            }
            if self.managed_ids:
                # On upgrade/reload the old always-visible management controls
                # can exist in the registry before this manager owns an entity.
                # Touch only exact IDs for devices in this entry's current data.
                registry = er.async_get(self.hass)
                for unique_id in self.managed_ids(self.coordinator) - wanted.keys():
                    entity_id = registry.async_get_entity_id(
                        self.platform_domain, DOMAIN, unique_id
                    )
                    entry = registry.async_get(entity_id) if entity_id else None
                    if (
                        entry
                        and entry.config_entry_id
                        == self.coordinator.config_entry.entry_id
                    ):
                        self._soft_delete_entry(entry)
            for unique_id in set(self.entities) - wanted.keys():
                entity = self.entities.pop(unique_id)
                self._soft_delete(entity)
                if entity.hass is not None and entity.entity_id:
                    await entity.async_remove(force_remove=True)
            added = []
            for unique_id, entity in wanted.items():
                if unique_id in self.entities:
                    continue
                self._restore_registry(entity)
                entity._manager = self
                self.entities[unique_id] = entity
                added.append(entity)
            if added:
                result = self.add_entities(added)
                if inspect.isawaitable(result):
                    await result

    async def async_stop(self):
        self._closed = True
        self._unsub()
        if (
            self._task
            and not self._task.done()
            and self._task is not asyncio.current_task()
        ):
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def async_pause(self):
        """Finish any current local entity registration before HA tears down."""
        self._paused = True
        if (
            self._task
            and not self._task.done()
            and self._task is not asyncio.current_task()
        ):
            await asyncio.gather(self._task, return_exceptions=True)

    def async_resume(self):
        self._paused = False
        self._schedule()


async def async_setup_entities(
    hass, entry, add_entities, factory, *, managed_ids=None, platform_domain=None
):
    try:
        platform = async_get_current_platform()
    except RuntimeError:
        platform = getattr(add_entities, "__self__", None)
    if isinstance(platform, EntityPlatform):
        # Await the real registration operation so a rapid delete/undo cannot
        # race two asynchronously scheduled objects with the same unique ID.
        add_entities = platform.async_add_entities
    manager = DynamicEntities(
        hass, entry.runtime_data, add_entities, factory, managed_ids, platform_domain
    )
    await manager.async_sync()
