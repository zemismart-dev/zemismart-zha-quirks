"""Zemismart three-channel dimmer, TS0601/_TZE204_znvwzxkq.

Protocol source: zigbee-herdsman-converters commit
760419e7e078c7ab44a3d606e58a46c51e6cfcb3, src/devices/tuya.ts
(TS0601_dimmer_3, upstream fingerprint alias ZN2S-RS3E-DH) and src/lib/tuya.ts.
The official dimmer family lists ZN2S-RS3E-DH / ZN2S-US3U-DH; the exact
inventory SKU is unconfirmed. The earlier screenshot title ZN-USC1U-HT
belongs to a curtain switch, so it is not used as this device's model.
DP26 backlight switch, DP104 child lock and 10..1000 brightness-limit ranges
are supported by the same-fingerprint Tuya Cloud data in
https://github.com/Koenkk/zigbee2mqtt/issues/21940#issuecomment-2029260308
and the local BOOL / VALUE reports. Their physical effects remain unverified.
Native ZHA transport reviewed at
zha-device-handlers 8c8e861c9bf8e4eb389fb42ecdc00cfe3a893452.
Tested against zha-quirks 2.2.0, zha 2.1.0 and zigpy 2.1.0.

The September 28, 2026 interview (application version 70) and passive reports
confirm the topology and the datatypes of the implemented DPs. Endpoints 2/3
are local light representations; every Tuya command uses physical endpoint 1.

DP4/10 are raw read-only diagnostic attributes, without configuration entities.
The observed device reports DP4 twice around DP10 in full status bursts, and
DP4 also reports undefined 0x80/0x81 values after lamp-type commands. Preserve
these values without masking; the last DP4 report cannot prove channel 1's
lamp type or successful restoration. No lamp-type writing is exposed.

DP18 is deliberately unmapped: upstream calls it channel 3 light type, but
this firmware reports a four-byte VALUE instead of ENUM. DP20 (upstream's
channel 3 countdown) was not reported. Neither gets a writable entity until
this conflict is resolved. DP102's mode options and DP105's meaning remain
unresolved, so neither gets a writable entity.
Source and report replay tests do not establish physical operation.
"""

from zigpy.device import Device
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation

from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaLevelControl, TuyaMCUCluster, TuyaOnOffNM

MANUFACTURER = "_TZE204_znvwzxkq"
MODEL = "TS0601"


class ZemismartDimmerMCU(TuyaMCUCluster):
    """Keep ambiguous lamp-type reports available without permitting writes."""

    async def write_attributes(self, attributes, manufacturer=UNDEFINED, **kwargs):
        """Enforce read-only access before Tuya updates the cache or sends DPs."""
        writable = {}
        failures = []
        for key, value in attributes.items():
            attribute = self.find_attribute(key)
            if attribute.id in (0xEF04, 0xEF0A):
                failures.append(
                    foundation.WriteAttributesStatusRecord(
                        foundation.Status.READ_ONLY, attribute.id
                    )
                )
            else:
                writable[key] = value
        if not failures:
            return await super().write_attributes(
                attributes, manufacturer=manufacturer, **kwargs
            )
        if writable:
            result = await super().write_attributes(
                writable, manufacturer=manufacturer, **kwargs
            )
            failures.extend(
                record for record in result[0]
                if record.status != foundation.Status.SUCCESS
            )
        return [failures]


class PowerOnBehavior(t.enum8):
    """State to restore after power returns."""

    off = 0
    on = 1
    previous = 2


class BacklightMode(t.enum8):
    """Backlight relationship to the dimmer state."""

    off = 0
    normal = 1
    inverted = 2


class BacklightColor(t.enum8):
    """Colors from the upstream BacklightColorEnum."""

    red = 0
    blue = 1
    green = 2
    white = 3
    yellow = 4
    magenta = 5
    cyan = 6
    warm_white = 7


def matches_interview(device: Device) -> bool:
    """Require the observed topology and avoid overwriting real endpoints 2/3."""
    endpoint = device.endpoints.get(1)
    return (
        set(device.endpoints) == {0, 1}
        and endpoint is not None
        and endpoint.profile_id == zha.PROFILE_ID
        and endpoint.device_type == zha.DeviceType.SMART_PLUG
        and {0x0000, 0x0004, 0x0005, 0xEF00}.issubset(endpoint.in_clusters)
        and {0x000A, 0x0019}.issubset(endpoint.out_clusters)
    )


def brightness_from_dp(value: int) -> int:
    """Convert Tuya 0..1000 into standard ZCL level 0..254."""
    return round(min(1000, max(0, value)) * 254 / 1000)


def brightness_to_dp(value: int) -> int:
    """Keep full brightness within Tuya's 1000 maximum, including HA's 255."""
    return round(min(254, max(0, value)) * 1000 / 254)


_builder = (
    TuyaQuirkBuilder(MANUFACTURER, MODEL)
    .filter(matches_interview)
    .friendly_name(manufacturer="Zemismart", model="TS0601 3-gang dimmer")
    .replaces_endpoint(1, device_type=zha.DeviceType.DIMMABLE_LIGHT)
    .adds_endpoint(2, device_type=zha.DeviceType.DIMMABLE_LIGHT)
    .adds_endpoint(3, device_type=zha.DeviceType.DIMMABLE_LIGHT)
    .skip_configuration()
)

for _endpoint, _state_dp, _level_dp, _min_dp, _max_dp in (
    (1, 1, 2, 3, 5),
    (2, 7, 8, 9, 11),
    (3, 15, 16, 17, 19),
):
    _builder.adds(TuyaOnOffNM, endpoint_id=_endpoint).adds(
        TuyaLevelControl, endpoint_id=_endpoint
    ).tuya_dp(
        _state_dp, "on_off", "on_off", endpoint_id=_endpoint
    ).tuya_dp(
        _level_dp,
        "level",
        "current_level",
        converter=brightness_from_dp,
        dp_converter=brightness_to_dp,
        endpoint_id=_endpoint,
    )
    for _dp, _limit in ((_min_dp, "minimum"), (_max_dp, "maximum")):
        _builder.tuya_number(
            _dp,
            type=t.uint32_t,
            attribute_name=f"{_limit}_brightness_l{_endpoint}",
            min_value=1,
            max_value=100,
            step=1,
            unit="%",
            multiplier=0.1,
            translation_key=f"{_limit}_brightness_l{_endpoint}",
            fallback_name=f"Channel {_endpoint} {_limit} brightness",
        )

for _endpoint, _type_dp, _countdown_dp in ((1, 4, 6), (2, 10, 12)):
    _builder.tuya_dp_attribute(
        _type_dp,
        attribute_name=f"light_type_dp{_type_dp}_raw",
        type=t.uint8_t,
        access=foundation.ZCLAttributeAccess.Read,
    ).tuya_number(
        _countdown_dp,
        type=t.uint32_t,
        attribute_name=f"countdown_l{_endpoint}",
        min_value=0,
        max_value=43200,
        step=1,
        unit="s",
        translation_key=f"countdown_l{_endpoint}",
        fallback_name=f"Channel {_endpoint} countdown",
    )

QUIRK = (
    _builder.tuya_enum(
        14,
        attribute_name="power_on_behavior",
        enum_class=PowerOnBehavior,
        translation_key="power_on_behavior",
        fallback_name="Power on behavior",
    )
    .tuya_enum(
        21,
        attribute_name="backlight_mode",
        enum_class=BacklightMode,
        translation_key="backlight_mode",
        fallback_name="Backlight mode",
    )
    .tuya_switch(
        26,
        attribute_name="backlight_switch",
        translation_key="backlight",
        fallback_name="Backlight",
    )
    .tuya_enum(
        101,
        attribute_name="backlight_color",
        enum_class=BacklightColor,
        translation_key="backlight_color",
        fallback_name="Backlight color",
    )
    .tuya_number(
        103,
        type=t.uint32_t,
        attribute_name="backlight_brightness",
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        translation_key="backlight_brightness",
        fallback_name="Backlight brightness",
    )
    .tuya_switch(
        104,
        attribute_name="child_lock",
        translation_key="child_lock",
        fallback_name="Child lock",
    )
    .add_to_registry(replacement_cluster=ZemismartDimmerMCU)
)
