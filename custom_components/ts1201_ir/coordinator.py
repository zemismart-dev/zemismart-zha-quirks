"""Read quirk snapshots and bind only to current, available ZHA objects."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.components.zha.helpers import (
    get_config_entry as get_zha_config_entry,
)
from homeassistant.components.zha.helpers import get_zha_gateway
from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from zha.application.gateway import ConnectionLostEvent
from zigpy.zcl import AttributeUpdatedEvent

from .const import (
    ACTION_NAMES,
    CLIMATE_REVISION_ATTRIBUTE,
    DOMAIN,
    KEY_REVISION_ATTRIBUTE,
    MANUFACTURER,
    MATCH_CLUSTER_ID,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Binding:
    """One current ZHA object graph and its cancellable event subscriptions."""

    ieee: str
    gateway: Any
    device: Any
    cluster: Any
    unsubs: list[Callable] = field(default_factory=list)
    active: bool = False


def _panel_snapshot(value: dict) -> dict:
    """Keep UI metadata only; never copy a raw code into HA state/Recorder."""
    if value.get("version") != 1 or not isinstance(value.get("keys"), list):
        raise ValueError("Unsupported TS1201 key snapshot")
    keys = []
    for key in value["keys"]:
        key_id = str(key["id"])
        if not key_id.isdecimal() or int(key_id) < 1:
            raise ValueError("Invalid TS1201 key ID")
        keys.append({"id": key_id, "name": str(key["name"])})
    return {
        "version": 1,
        "revision": value.get("revision", 0),
        "name": str(value.get("name", "")),
        "selected_id": str(value["selected_id"])
        if value.get("selected_id") is not None
        else None,
        "keys": keys,
        "count": len(keys),
        "status": str(value.get("status", ""))[:250],
        "learning": bool(value.get("learning", False)),
        "busy": bool(value.get("busy", False)),
        "pending_valid": bool(value.get("pending_valid", False)),
        "pending_expires_at": value.get("pending_expires_at"),
        "can_undo": bool(value.get("can_undo", False)),
        "relevant_actions": [
            action
            for action in value.get("relevant_actions", [])
            if action in ACTION_NAMES
        ],
    }


def _climate_panel_snapshot(cluster) -> dict:
    """Copy only public control metadata; never expose the underlying IR table."""
    if not all(
        callable(getattr(cluster, name, None))
        for name in ("climate_snapshot", "climate_action")
    ):
        return {"version": 1, "available": False}
    value = cluster.climate_snapshot()
    if value.get("version") != 1:
        return {"version": 1, "available": False}
    temperature = value.get("temperature") or {}
    constraints = value.get("mode_constraints") or {}

    def settings(name):
        state = value.get(name)
        return (
            {key: state.get(key) for key in ("power", "mode", "temperature", "fan")}
            if state
            else None
        )

    return {
        "version": 1,
        "available": bool(value.get("available", False)),
        # Backend availability also reflects its runtime activation. Retain the
        # entity across an outage while the confirmed capabilities still exist.
        "supported": bool(
            value.get("codebook_id")
            and value.get("modes")
            and value.get("desired")
            and temperature.get("values")
        ),
        "codebook_id": value.get("codebook_id"),
        "label": value.get("label", ""),
        "modes": list(value.get("modes", [])),
        "fans": list(value.get("fans", [])),
        "temperature": {
            **{key: temperature.get(key) for key in ("min", "max", "step")},
            "values": list(temperature.get("values", [])),
            "applicable": bool(temperature.get("applicable", False)),
        },
        "mode_constraints": {
            key: constraints[key]
            for key in ("fanControllable", "temperatureApplicable", "fixedFan")
            if key in constraints
        },
        "desired": settings("desired"),
        "estimated": settings("estimated"),
        "requested": settings("requested"),
        "pending": bool(value.get("pending", False)),
        "estimate_stale": bool(value.get("estimate_stale", False)),
        "status": str(value.get("status", ""))[:250],
    }


class Ts1201Coordinator(DataUpdateCoordinator):
    """Discover locally and delegate every mutation to the existing quirk."""

    def __init__(self, hass, entry):
        """Initialize without requiring a paired device."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
            always_update=True,
        )
        self.data = {}
        self.bindings: dict[str, Binding] = {}
        self.managers = []
        self._gateway = None
        self._blocked_gateway = None
        self._gateway_unsub = None
        self._entry = None
        self._entry_unsub = None
        self._unsubs = []
        self._refresh_task = None
        self._refresh_again = False
        self._actions: dict[asyncio.Task, Binding] = {}
        self._closed = False
        self._paused = False

    async def async_start(self):
        """Listen for lifecycle changes and perform one read-only scan."""
        self._unsubs.append(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_CONFIG_ENTRY_CHANGED,
                self._config_event,
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(
                EVENT_HOMEASSISTANT_STOP,
                self._hass_stop,
            )
        )
        await self.async_config_entry_first_refresh()

    async def _hass_stop(self, _event):
        await self.async_stop(whole_hass_shutdown=True)

    def _attach_entry(self):
        entries = (
            self.hass.config_entries.async_entries("zha")
            if self.hass.config_entries
            else []
        )
        try:
            entry = get_zha_config_entry(self.hass)
        except ValueError:
            entry = next(
                (item for item in entries if item.state is ConfigEntryState.LOADED),
                entries[0] if entries else None,
            )
        if entry is self._entry:
            return
        if self._entry_unsub:
            self._entry_unsub()
        self._entry = entry
        self._entry_unsub = (
            entry.async_on_state_change(self._entry_changed) if entry else None
        )

    @callback
    def _config_event(self, _change, entry):
        if entry.domain != "zha" or self._closed:
            return
        if entry is self._entry:
            self._entry_changed()
        else:
            self._queue_refresh()

    @callback
    def _entry_changed(self):
        if self._closed:
            return
        if self._entry and self._entry.state is not ConfigEntryState.LOADED:
            self._blocked_gateway = self._gateway
            self._detach_gateway(deactivate=True)
            self.async_set_updated_data(
                {
                    ieee: {**record, "available": False}
                    for ieee, record in self.data.items()
                }
            )
        else:
            self._blocked_gateway = None
        self._queue_refresh()

    def _read_gateway(self):
        if self._closed or (
            self._entry and self._entry.state is not ConfigEntryState.LOADED
        ):
            return None
        try:
            gateway = get_zha_gateway(self.hass)
        except (ValueError, KeyError):
            return None
        if gateway is self._blocked_gateway or getattr(gateway, "shutting_down", False):
            return None
        if (
            hasattr(gateway, "application_controller")
            and gateway.application_controller is None
        ):
            return None
        return gateway

    @staticmethod
    def _matcher(device):
        if device.manufacturer != MANUFACTURER or device.model != MODEL:
            return None
        endpoint = device.device.endpoints.get(1)
        if endpoint is None:
            return None
        cluster = endpoint.in_clusters.get(MATCH_CLUSTER_ID)
        if cluster is None or getattr(endpoint, "ir_match", None) is not cluster:
            return None
        if not all(
            callable(getattr(cluster, name, None))
            for name in ("key_snapshot", "key_action", "activate", "deactivate")
        ):
            return None
        return cluster

    def _same_source(self, binding):
        gateway = self._read_gateway()
        if gateway is not binding.gateway:
            return False
        device = gateway.devices.get(binding.device.ieee)
        return device is binding.device and self._matcher(device) is binding.cluster

    def is_available(self, ieee, key_id=None):
        """Recheck identity even before a scheduled lifecycle refresh executes."""
        binding = self.bindings.get(ieee)
        if (
            self._paused
            or not self.last_update_success
            or not binding
            or not binding.active
            or not self._same_source(binding)
            or not binding.device.available
        ):
            return False
        if key_id is not None:
            return any(
                key["id"] == key_id for key in self.snapshot(ieee).get("keys", [])
            )
        return True

    def snapshot(self, ieee):
        """Return cached UI metadata, never a second persistent key bank."""
        return self.data.get(ieee, {}).get("snapshot", {})

    def climate_snapshot(self, ieee):
        """Return the latest backend-owned state and mode-specific capabilities."""
        return self.data.get(ieee, {}).get("climate", {"available": False})

    def parent_device_id(self, ieee):
        """Resolve the actual ZHA parent within its own config-entry scope."""
        if not self._entry or self._entry.state is not ConfigEntryState.LOADED:
            return None
        try:
            return dr.async_get_device_id_by_identifier(
                self.hass,
                ("zha", ieee),
                config_entry_id=self._entry.entry_id,
            )
        except (ValueError, RuntimeError):
            return None

    def _update_parent_link(self, ieee):
        """Handle a ZHA parent appearing after the companion entity was added."""
        if not (parent_id := self.parent_device_id(ieee)):
            return
        registry = dr.async_get(self.hass)
        child = registry.async_get_device_by_identifier(
            (DOMAIN, ieee), self.config_entry.entry_id
        )
        if child is not None and child.via_device_id != parent_id:
            registry.async_update_device(child.id, via_device_id=parent_id)

    def _detach_binding(self, binding, *, deactivate):
        for unsub in binding.unsubs:
            unsub()
        binding.unsubs.clear()
        for task, owner in list(self._actions.items()):
            if owner is binding:
                task.cancel()
        if deactivate and binding.active:
            binding.cluster.deactivate()
        binding.active = False

    def _detach_gateway(self, *, deactivate):
        if self._gateway_unsub:
            self._gateway_unsub()
            self._gateway_unsub = None
        for binding in list(self.bindings.values()):
            self._detach_binding(binding, deactivate=deactivate)
        self.bindings.clear()
        self._gateway = None

    def _gateway_event(self, gateway, event):
        if gateway is not self._gateway or self._closed:
            return
        if isinstance(event, ConnectionLostEvent):
            self._blocked_gateway = gateway
            self._detach_gateway(deactivate=True)
            self.async_set_updated_data(
                {
                    ieee: {**record, "available": False}
                    for ieee, record in self.data.items()
                }
            )
        self._queue_refresh()

    def _cluster_event(self, binding, event):
        if self._closed or self.bindings.get(binding.ieee) is not binding:
            return
        if event.attribute_id in (KEY_REVISION_ATTRIBUTE, CLIMATE_REVISION_ATTRIBUTE):
            self._queue_refresh()

    @callback
    def _queue_refresh(self, *_args):
        if self._closed or self._paused:
            return
        self._refresh_again = True
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = self.hass.async_create_task(
            self._drain_refresh(), f"{DOMAIN} refresh"
        )

    async def _drain_refresh(self):
        while self._refresh_again and not self._closed:
            self._refresh_again = False
            await self.async_refresh()

    async def _async_update_data(self):
        if self._paused:
            return {
                ieee: {**record, "available": False}
                for ieee, record in self.data.items()
            }
        self._attach_entry()
        gateway = self._read_gateway()
        if gateway is not self._gateway:
            self._detach_gateway(deactivate=True)
            self._gateway = gateway
            if gateway and callable(getattr(gateway, "on_event", None)):
                self._gateway_unsub = gateway.on_event(
                    ConnectionLostEvent.event_type,
                    lambda event: self._gateway_event(gateway, event),
                )
        if gateway is None:
            return {
                ieee: {**record, "available": False}
                for ieee, record in self.data.items()
            }
        discovered = {}
        present = set()
        for device in list(gateway.devices.values()):
            cluster = self._matcher(device)
            if cluster is None:
                continue
            ieee = str(device.ieee)
            present.add(ieee)
            binding = self.bindings.get(ieee)
            if binding and (
                binding.device is not device or binding.cluster is not cluster
            ):
                self._detach_binding(binding, deactivate=True)
                binding = None
            if binding is None:
                binding = Binding(ieee, gateway, device, cluster)
                self.bindings[ieee] = binding
                binding.unsubs.append(
                    cluster.on_event(
                        AttributeUpdatedEvent.event_type,
                        lambda event, owner=binding: self._cluster_event(owner, event),
                    )
                )
                if callable(getattr(device, "on_all_events", None)):
                    binding.unsubs.append(device.on_all_events(self._queue_refresh))
            if device.available and not binding.active:
                binding.active = True
                cluster.activate()
            elif not device.available and binding.active:
                binding.active = False
                for task, owner in list(self._actions.items()):
                    if owner is binding:
                        task.cancel()
                cluster.deactivate()
            previous = self.data.get(ieee)
            discovered[ieee] = {
                # Retain membership while offline. Deactivation cancels an
                # unfinished capture but must not remove its visible controls.
                "snapshot": previous["snapshot"]
                if not device.available and previous
                else _panel_snapshot(cluster.key_snapshot()),
                "climate": _climate_panel_snapshot(cluster),
                "available": bool(device.available),
            }
            self._update_parent_link(ieee)
        for ieee in set(self.bindings) - present:
            self._detach_binding(self.bindings.pop(ieee), deactivate=True)
        return discovered

    async def async_key_action(self, ieee, action, value=None):
        """Resolve and verify the current object immediately before invoking it."""
        if self._closed or self._paused:
            raise HomeAssistantError("红外按键面板已卸载")
        await self.async_refresh()
        if not self.is_available(ieee):
            raise HomeAssistantError("ZHA 设备不可用或正在重新加载，请等待重新连接")
        binding = self.bindings[ieee]
        if (
            action == "send"
            and value is not None
            and not self.is_available(ieee, str(value))
        ):
            raise HomeAssistantError("该按键已删除或不存在")
        task = asyncio.current_task()
        self._actions[task] = binding
        try:
            await binding.cluster.key_action(action, value)
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        finally:
            self._actions.pop(task, None)
            if not self._closed and not self._paused:
                await self.async_refresh()

    async def async_climate_action(self, ieee, patch):
        """Delegate one atomic control patch after checking the current binding."""
        if self._closed or self._paused:
            raise HomeAssistantError("红外遥控器面板已卸载")
        await self.async_refresh()
        if not self.is_available(ieee) or not self.climate_snapshot(ieee).get(
            "available"
        ):
            raise HomeAssistantError("空调控制尚未就绪；请先完成码库匹配并确认设备在线")
        binding = self.bindings[ieee]
        if not callable(getattr(binding.cluster, "climate_action", None)):
            raise HomeAssistantError("当前 quirk 不提供空调控制接口")
        task = asyncio.current_task()
        self._actions[task] = binding
        try:
            await binding.cluster.climate_action(dict(patch))
        except ValueError as error:
            raise HomeAssistantError(str(error)) from error
        finally:
            self._actions.pop(task, None)
            if not self._closed and not self._paused:
                await self.async_refresh()

    async def async_begin_unload(self):
        """Quiesce before platform teardown, without irreversibly closing state."""
        self._paused = True
        tasks = list(self._actions)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for manager in self.managers:
            await manager.async_pause()

    async def async_abort_unload(self):
        """Restore a still-loaded panel if HA could not unload its platforms."""
        self._paused = False
        await self.async_refresh()
        for manager in self.managers:
            manager.async_resume()

    async def async_stop(self, *, whole_hass_shutdown=False):
        """Unsubscribe completely, preserving a still-current native ZHA quirk."""
        if self._closed:
            return
        current_gateway = self._read_gateway()
        self._closed = True
        for manager in self.managers:
            await manager.async_stop()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._entry_unsub:
            self._entry_unsub()
            self._entry_unsub = None
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
        tasks = list(self._actions)
        self._detach_gateway(
            deactivate=whole_hass_shutdown or current_gateway is not self._gateway
        )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.async_shutdown()
