"""ZHA support for the Zemismart ZN2S-US01U-ZK switch.

The user identified the commercial model from the product image associated
with this unit's 2026-09-28 ZHA interview: TS0601 / _TZE284_rzdkn5rx.
The exact fingerprint in zemismart-dev/zigbee2mqtt zms206.js, revision
e92cc094075dfd3fc58f886a8406f39e1a3a7438, agrees with this unit's reports
on DP1/7/15/16/29/101/102/103/104. That converter's filename is not the
commercial model. DP29 is the relay's power-on behaviour; the generic Moes
DP14 mapping does not describe this unit.

DP19 arrived as an empty STRING and DP209/210 as empty RAW values. They
remain diagnostic caches, without configuration entities or inferred meaning.
Advanced attribute writes to these caches are explicitly rejected as READ_ONLY.
DP105 name writing is deliberately absent until independently verified.
The different _TZE28C1000000_rzdkn5rx fingerprint is not included.
"""

from __future__ import annotations

from zha.application import EntityType
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaMCUCluster
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation

MANUFACTURER = "_TZE284_rzdkn5rx"
MODEL = "TS0601"


class ZemismartSwitchMCU(TuyaMCUCluster):
    """Retain unknown datapoint reports without permitting attribute writes."""

    async def write_attributes(self, attributes, manufacturer=UNDEFINED, **kwargs):
        """Reject unknown writes before Tuya changes the cache or sends DPs."""
        writable = {}
        failures = []
        for key, value in attributes.items():
            attribute = self.find_attribute(key)
            if attribute.name in {"unknown_dp19", "unknown_dp209", "unknown_dp210"}:
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


class IndicatorMode(t.enum8):
    """DP15 indicator behaviour, matching the company converter."""

    off = 0
    on_off_status = 1
    switch_position = 2


class PowerOnBehavior(t.enum8):
    """DP29 relay behaviour after a power interruption."""

    power_off = 0
    power_on = 1
    restart_memory = 2


class IndicatorColor(t.enum8):
    """DP103/104 off/on indicator colours, matching the company converter."""

    red = 0
    blue = 1
    green = 2
    white = 3
    yellow = 4
    magenta = 5
    cyan = 6
    warm_white = 7
    warm_yellow = 8


def _has_tuya_endpoint(device) -> bool:
    """Require the observed HA endpoint and Tuya protocol cluster."""
    endpoint = device.endpoints.get(1)
    return (
        endpoint is not None
        and endpoint.profile_id == zha.PROFILE_ID
        and 0xEF00 in endpoint.in_clusters
    )


QUIRK = (
    TuyaQuirkBuilder(MANUFACTURER, MODEL)
    .friendly_name(manufacturer="Zemismart", model="ZN2S-US01U-ZK")
    .filter(_has_tuya_endpoint)
    .tuya_enchantment(data_query_spell=True)
    .tuya_switch(
        dp_id=1,
        attribute_name="relay_state",
        entity_type=EntityType.STANDARD,
        translation_key="relay_state",
        fallback_name="Relay",
    )
    .tuya_number(
        dp_id=7,
        type=t.uint32_t,
        attribute_name="countdown",
        min_value=0,
        max_value=43200,
        step=1,
        unit="s",
        translation_key="countdown",
        fallback_name="Countdown",
    )
    .tuya_enum(
        dp_id=15,
        attribute_name="indicator_mode",
        enum_class=IndicatorMode,
        translation_key="indicator_mode",
        fallback_name="Indicator mode",
    )
    .tuya_switch(
        dp_id=16,
        attribute_name="backlight",
        translation_key="backlight",
        fallback_name="Backlight",
    )
    .tuya_enum(
        dp_id=29,
        attribute_name="power_on_behavior",
        enum_class=PowerOnBehavior,
        translation_key="power_on_behavior",
        fallback_name="Power-on behavior",
    )
    .tuya_switch(
        dp_id=101,
        attribute_name="child_lock",
        translation_key="child_lock",
        fallback_name="Child lock",
    )
    .tuya_number(
        dp_id=102,
        type=t.uint32_t,
        attribute_name="backlight_brightness",
        min_value=0,
        max_value=100,
        step=1,
        unit="%",
        translation_key="backlight_brightness",
        fallback_name="Backlight brightness",
    )
    .tuya_enum(
        dp_id=103,
        attribute_name="indicator_color_off",
        enum_class=IndicatorColor,
        translation_key="indicator_color_off",
        fallback_name="Indicator color while off",
    )
    .tuya_enum(
        dp_id=104,
        attribute_name="indicator_color_on",
        enum_class=IndicatorColor,
        translation_key="indicator_color_on",
        fallback_name="Indicator color while on",
    )
    .tuya_dp_attribute(
        dp_id=19,
        attribute_name="unknown_dp19",
        type=t.CharacterString,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .tuya_dp_attribute(
        dp_id=209,
        attribute_name="unknown_dp209",
        type=t.LVBytes,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .tuya_dp_attribute(
        dp_id=210,
        attribute_name="unknown_dp210",
        type=t.LVBytes,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .skip_configuration()
    .add_to_registry(replacement_cluster=ZemismartSwitchMCU)
)
