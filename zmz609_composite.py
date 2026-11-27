"""ZHA quirk for the Zemismart ZMZ609 six-key display switch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import zigpy.types as t
from zha.application import EntityType
from zha.exceptions import ZHAException
from zhaquirks.const import (
    CLUSTER_ID,
    COMMAND,
    ENDPOINT_ID,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.device import CustomZigpyDevice
from zhaquirks.tuya import (
    TUYA_CLUSTER_ID,
    BaseEnchantedDevice,
    TuyaDatapointData,
    TuyaDPType,
)
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaClusterData, TuyaMCUCluster, TuyaOnOffNM
from zigpy.profiles import zha
from zigpy.typing import UNDEFINED, UndefinedType
from zigpy.zcl import foundation

MANUFACTURER = "_TZE28C1000000_t4zhrymg"
MODEL = "TS0601"
KEYS = range(1, 7)
MODE_CONTROL_KEYS = (1, 2)
MODE_CONTROL_ATTRIBUTES = {f"switch_mode_l{key}" for key in MODE_CONTROL_KEYS}
SCENE_NAME_DPS = (111, 112, 113, 114, 103, 104)
POWER_ON_COUNT_DP = 123
POWER_ON_COUNT = "power_on_count"
WEATHER_REQUEST_EVENT = "zmz609_weather_request"


class SwitchMode(t.enum8):
    """Select what the corresponding physical key does."""

    switch = 0
    scene = 1


def _track_ha_control_visibility(
    cluster: ZMZ609CompositeMCUCluster,
) -> Callable[[int], None] | None:
    """Keep the local HA device page in sync with the confirmed modes."""
    try:
        from homeassistant.components.zha.helpers import get_zha_data
        from homeassistant.core import async_get_hass_or_none, callback
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er
    except ImportError:
        return None

    hass = async_get_hass_or_none()
    if hass is None or (config_entry := get_zha_data(hass).config_entry) is None:
        return None

    ieee = str(cluster.endpoint.device.ieee)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    controls = {
        key: (
            (SwitchMode.switch, "switch", f"{ieee}-{key}"),
            (SwitchMode.scene, "button", f"{ieee}-1-scene_{key}"),
        )
        for key in MODE_CONTROL_KEYS
    }
    key_by_control = {
        (domain, unique_id): key
        for key, specs in controls.items()
        for _, domain, unique_id in specs
    }
    tracked = hass.data.setdefault("zemismart_zmz609_control_visibility", {})
    if previous := tracked.get(ieee):
        previous()
    managed_device_id: str | None = None

    def lookup(domain: str, unique_id: str) -> er.RegistryEntry | None:
        if entity_id := entities.async_get_entity_id(domain, "zha", unique_id):
            entity = entities.async_get(entity_id)
            if entity and entity.config_entry_id == config_entry.entry_id:
                return entity
        return None

    @callback
    def reconcile(key: int) -> None:
        nonlocal managed_device_id
        if tracked.get(ieee) is not stop:
            return
        device = devices.async_get_device(identifiers={("zha", ieee)})
        if device is None or config_entry.entry_id not in device.config_entries:
            return
        managed_device_id = device.id
        mode = cluster.get(f"switch_mode_l{key}")
        # Detach the inactive control first. The device page lists associated entities.
        for expected, domain, unique_id in sorted(
            controls[key], key=lambda spec: spec[0] == mode
        ):
            entity = lookup(domain, unique_id)
            if entity is None or entity.device_id not in (None, device.id):
                continue
            active = mode == expected
            device_id = device.id if active else None
            hidden_by = entity.hidden_by
            if hidden_by != er.RegistryEntryHider.USER:
                hidden_by = None if active else er.RegistryEntryHider.INTEGRATION
            if (entity.device_id, entity.hidden_by) != (device_id, hidden_by):
                entities.async_update_entity(
                    entity.entity_id, device_id=device_id, hidden_by=hidden_by
                )

    @callback
    def entity_changed(event) -> None:
        if event.data["action"] != "create" and "device_id" not in event.data.get(
            "changes", {}
        ):
            return
        entity = entities.async_get(event.data["entity_id"])
        if (
            entity
            and entity.platform == "zha"
            and (key := key_by_control.get((entity.domain, entity.unique_id)))
        ):
            hass.loop.call_soon(reconcile, key)

    @callback
    def device_removed(event) -> None:
        if (
            event.data["action"] != "remove"
            or event.data["device_id"] != managed_device_id
        ):
            return
        for domain, unique_id in key_by_control:
            if (entity := lookup(domain, unique_id)) and entity.device_id is None:
                entities.async_remove(entity.entity_id)
        stop()

    stop_entities = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, entity_changed
    )
    stop_devices = hass.bus.async_listen(
        dr.EVENT_DEVICE_REGISTRY_UPDATED, device_removed
    )

    @callback
    def stop() -> None:
        if tracked.get(ieee) is stop:
            tracked.pop(ieee)
            stop_entities()
            stop_devices()

    tracked[ieee] = stop
    config_entry.async_on_unload(stop)
    for key in MODE_CONTROL_KEYS:
        hass.loop.call_soon(reconcile, key)
    return reconcile


class _ModeAwareOnOff(TuyaOnOffNM):
    """Apply switch mode to relay controls for the first two keys."""

    async def command(self, command_id, *args, **kwargs):
        """Only drive an output when its key is in switch mode."""
        if command_id in (0, 1):
            key = self.endpoint.endpoint_id
            cluster = self.endpoint.device.endpoints[1].tuya_manufacturer
            if cluster.control_mode(key) != SwitchMode.switch:
                raise ZHAException(f"Key {key} is not in switch mode")
        return await super().command(command_id, *args, **kwargs)


class PowerOnBehavior(t.enum8):
    """Restore state after power is applied."""

    off = 0
    on = 1
    previous = 2


class ScreenOffTime(t.enum8):
    """Time before the display turns off."""

    disabled = 0
    seconds_10 = 1
    seconds_20 = 2
    seconds_30 = 3
    seconds_45 = 4
    seconds_60 = 5


class RadarDistance(t.enum8):
    """Distance at which the radar activates the display."""

    short = 0
    medium_short = 1
    medium = 2
    medium_long = 3
    long = 4


class _RawScreenName(bytes):
    """UTF-8 bytes for a Tuya RAW datapoint."""

    def serialize(self) -> bytes:
        """Return the bytes that TuyaData wraps with a type and length."""
        return bytes(self)


def _decode_screen_name(value: bytes) -> str:
    """Decode the display name reported by this panel."""
    return value.decode("utf-8", errors="replace").rstrip("\x00")


def _encode_screen_name(value: str) -> _RawScreenName:
    """Encode the display name using datapoint type RAW."""
    return _RawScreenName(value.encode("utf-8"))


class _ScreenNameClusterData(TuyaClusterData):
    """Carry text through the Tuya command bus."""

    attr_value: t.CharacterString


class ZMZ609CompositeDevice(CustomZigpyDevice, BaseEnchantedDevice):
    """Run the initialization used by the six-key panel."""

    tuya_spell_read_attributes = True
    tuya_spell_data_query = True
    _initializing = False

    async def apply_custom_configuration(self, *args, **kwargs) -> None:
        """Avoid overlapping initialization from reconfigure and power reports."""
        if self._initializing:
            return
        self._initializing = True
        try:
            await super().apply_custom_configuration(*args, **kwargs)
        finally:
            self._initializing = False

    async def spell_attribute_reads(self) -> None:
        """Send the Basic attributes in the single frame this panel expects."""
        await self.endpoints[1].basic.read_attributes_raw(
            [4, 0, 1, 5, 7, 0xFFFE], manufacturer=None
        )


class ZMZ609CompositeMCUCluster(TuyaMCUCluster):
    """Handle scene presses, weather requests, and display names."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pending_modes: set[str] = set()
        self._reconcile_ha_control = _track_ha_control_visibility(self)

    class ServerCommandDefs(TuyaMCUCluster.ServerCommandDefs):
        """Commands the gateway sends to the panel."""

        weather_sync = foundation.ZCLCommandDef(
            id=0x61, schema={"payload": t.SerializableBytes}, manufacturer_code=None
        )

    class ClientCommandDefs(TuyaMCUCluster.ClientCommandDefs):
        """Commands the panel sends to the gateway."""

        weather_request = foundation.ZCLCommandDef(
            id=0x60, schema={"payload": t.List[t.uint8_t]}, manufacturer_code=None
        )

    def handle_weather_request(self, payload: t.List[t.uint8_t]) -> foundation.Status:
        """Forward a request for an icon from each requested weather slot."""
        data = bytes(payload)
        if len(data) != 9 or data[2:6] != b"\x11\x00\x03\x12" or data[7] != 0x13:
            return foundation.Status.INVALID_FIELD
        forecast_days, current_weather = data[6], data[8]
        if (
            forecast_days > 7
            or current_weather not in (0, 1)
            or not (forecast_days or current_weather)
        ):
            return foundation.Status.INVALID_FIELD
        self.listener_event(
            ZHA_SEND_EVENT,
            WEATHER_REQUEST_EVENT,
            {
                "prefix": data[:2].hex(),
                "forecast_days": forecast_days,
                "current_weather": bool(current_weather),
            },
        )
        return foundation.Status.SUCCESS

    def _handle_power_on_count(self, datapoint: TuyaDatapointData) -> None:
        """Repeat initialization after the panel reports a new power-on count."""
        if datapoint.data.dp_type != TuyaDPType.VALUE or len(datapoint.data.raw) != 4:
            return
        count = int.from_bytes(datapoint.data.raw, "big")
        previous_count = self.get(POWER_ON_COUNT)
        if count == previous_count:
            return
        self.update_attribute(POWER_ON_COUNT, count)
        if previous_count is not None:
            self.create_catching_task(self.endpoint.device.apply_custom_configuration())

    def _handle_scene_event(self, datapoint: TuyaDatapointData) -> None:
        """Publish a physical scene press as a ZHA event."""
        if datapoint.data.dp_type == TuyaDPType.ENUM and datapoint.data.raw == b"\x00":
            self._emit_scene(datapoint.dp)

    def _emit_scene(self, key: int) -> None:
        """Emit the same device trigger for both kinds of press."""
        self.listener_event(ZHA_SEND_EVENT, f"scene_{key}", {"button": f"button_{key}"})

    def control_mode(self, key: int):
        """Use the reported mode for both controls, including during a transition."""
        attribute = f"switch_mode_l{key}"
        return None if attribute in self._pending_modes else self.get(attribute)

    async def press_scene(self, key: int) -> None:
        """Execute a fixed scene or a key whose scene mode is confirmed."""
        if key not in KEYS or (
            key in MODE_CONTROL_KEYS and self.control_mode(key) != SwitchMode.scene
        ):
            raise ZHAException(f"Key {key} is not in scene mode")
        self._emit_scene(key)

    def _dp_2_attr_update(self, datapoint: TuyaDatapointData) -> None:
        """Unlock a mode only after receiving a valid device report."""
        key = datapoint.dp - 17
        if key in MODE_CONTROL_KEYS:
            if datapoint.data.dp_type != TuyaDPType.ENUM or datapoint.data.raw not in (
                b"\x00",
                b"\x01",
            ):
                return
            self._pending_modes.discard(f"switch_mode_l{key}")
        super()._dp_2_attr_update(datapoint)
        if key in MODE_CONTROL_KEYS and self._reconcile_ha_control is not None:
            self._reconcile_ha_control(key)

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Use the typed text payload for names and the standard path for other writes."""
        other_attributes = {}
        screen_names = {}
        confirmed_mode_writes = {}
        for record in self._write_attr_records(attributes):
            attribute = self.attributes[record.attrid]
            if attribute.type is t.CharacterString:
                screen_names[attribute.name] = record.value.value
            elif attribute.name in MODE_CONTROL_ATTRIBUTES:
                confirmed_mode_writes[attribute.name] = record.value.value
            else:
                other_attributes[attribute.name] = record.value.value

        if other_attributes:
            response = await super().write_attributes(
                other_attributes, manufacturer=manufacturer, **kwargs
            )
        else:
            response = [
                [foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]
            ]

        for attribute, value in screen_names.items():
            self.tuya_mcu_command(
                _ScreenNameClusterData(
                    endpoint_id=self.endpoint.endpoint_id,
                    cluster_name=self.ep_attribute,
                    cluster_attr=attribute,
                    attr_value=value,
                    expect_reply=False,
                    manufacturer=manufacturer,
                )
            )
        for attribute, value in confirmed_mode_writes.items():
            request = TuyaClusterData(
                endpoint_id=self.endpoint.endpoint_id,
                cluster_name=self.ep_attribute,
                cluster_attr=attribute,
                attr_value=value,
                expect_reply=False,
                manufacturer=manufacturer,
            )
            self._pending_modes.add(attribute)
            # Leave the select value at the last reported mode until the DP arrives.
            for cmd in self.from_cluster_data(request):
                await self.command(
                    self.mcu_write_command,
                    cmd,
                    expect_reply=False,
                    manufacturer=manufacturer,
                )
        return response


def _build_quirk() -> TuyaQuirkBuilder:
    """Map two switch controls and six scene triggers on physical endpoint 1."""
    builder = TuyaQuirkBuilder(MANUFACTURER, MODEL).friendly_name(
        manufacturer="Zemismart", model="ZMZ609-6"
    )
    builder.adds_endpoint(2, device_type=zha.DeviceType.ON_OFF_PLUG_IN_UNIT)
    for key in KEYS:
        if key in MODE_CONTROL_KEYS:
            builder.tuya_onoff(
                dp_id=23 + key,
                endpoint_id=key,
                onoff_cfg=_ModeAwareOnOff,
            )
            builder.tuya_enum(
                17 + key,
                f"switch_mode_l{key}",
                SwitchMode,
                translation_key=f"switch_mode_l{key}",
                fallback_name=f"Key {key} mode",
            )
        else:
            # The firmware reports both datapoints even for fixed scene keys.
            builder.tuya_dp_multi(17 + key, [])
            builder.tuya_dp_multi(23 + key, [])
        builder.command_button(
            "press_scene",
            TUYA_CLUSTER_ID,
            command_args=(key,),
            entity_type=EntityType.STANDARD,
            unique_id_suffix=f"scene_{key}",
            translation_key=f"scene_{key}",
            fallback_name=f"Scene {key}",
        )
        builder.tuya_dp_multi(key, [], dp_handler="_handle_scene_event")
        builder.tuya_number(
            29 + key,
            t.uint32_t,
            f"countdown_l{key}",
            min_value=0,
            max_value=43200,
            step=1,
            unit="s",
            translation_key=f"countdown_l{key}",
            fallback_name=f"Key {key} countdown",
        )
        builder.tuya_enum(
            38 + key,
            f"power_on_behavior_l{key}",
            PowerOnBehavior,
            translation_key=f"power_on_behavior_l{key}",
            fallback_name=f"Key {key} power-on behavior",
        )
        for dp_id, name in (
            (104 + key, f"switch{key}_name"),
            (SCENE_NAME_DPS[key - 1], f"scene{key}_name"),
        ):
            builder.tuya_dp_attribute(
                dp_id,
                name,
                converter=_decode_screen_name,
                dp_converter=_encode_screen_name,
                type=t.CharacterString,
                access=foundation.ZCLAttributeAccess.Read
                | foundation.ZCLAttributeAccess.Write,
            )

    builder.tuya_enum(
        38,
        "power_on_behavior",
        PowerOnBehavior,
        translation_key="power_on_behavior",
        fallback_name="Power-on behavior",
    )
    builder.tuya_switch(
        101, "child_lock", translation_key="child_lock", fallback_name="Child lock"
    )
    builder.tuya_number(
        102,
        t.uint32_t,
        "backlight",
        min_value=0,
        max_value=101,
        step=1,
        unit="%",
        translation_key="backlight",
        fallback_name="Backlight brightness",
    )
    builder.tuya_enum(
        120,
        "screen_off_time",
        ScreenOffTime,
        translation_key="screen_off_time",
        fallback_name="Screen-off time",
    )
    builder.tuya_enum(
        121,
        "radar_distance",
        RadarDistance,
        translation_key="radar_distance",
        fallback_name="Radar distance",
    )

    # Keep the power counter in the local cache without creating an entity or write mapping.
    builder.tuya_attribute(
        POWER_ON_COUNT_DP,
        POWER_ON_COUNT,
        type=t.uint32_t,
        access=foundation.ZCLAttributeAccess.Read
        | foundation.ZCLAttributeAccess.Report,
    )
    builder.tuya_dp_multi(POWER_ON_COUNT_DP, [], dp_handler="_handle_power_on_count")
    # The group binding payload is unverified. Elapsed runtime stays internal.
    for dp_id in (17, 125):
        builder.tuya_dp_multi(dp_id, [])

    return (
        builder.device_automation_triggers(
            {
                (SHORT_PRESS, f"button_{key}"): {
                    COMMAND: f"scene_{key}",
                    ENDPOINT_ID: 1,
                    CLUSTER_ID: TUYA_CLUSTER_ID,
                }
                for key in KEYS
            }
        )
        .skip_configuration()
        .zigpy_device_class(ZMZ609CompositeDevice)
    )


QUIRK = _build_quirk().add_to_registry(replacement_cluster=ZMZ609CompositeMCUCluster)
