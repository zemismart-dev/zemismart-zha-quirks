"""ZHA custom quirk for the Zemismart ZMD-206 screen dimmer family.

Validated three-gang DP contract:
``TS0601 / _TZE28C1000000_k9e7ihec``.

Additional exact three-gang fingerprint observed in a Zigbee2MQTT interview:
``TS0601 / _TZE284_k9e7ihec``. Its full functional surface is not yet
physically verified.

The 1- and 2-gang fingerprint variants share the observed channel DP stride.
All matching remains exact; this quirk never matches TS0601 broadly.
"""

from __future__ import annotations

import zigpy.types as t
from zigpy.profiles import zha

from zhaquirks.tuya import NoManufacturerCluster
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaInWallLevelControl, TuyaOnOffNM


BRIGHTNESS_MIN = 10
BRIGHTNESS_MAX = 1000
CHANNEL_DP_BASES = (1, 7, 15)


class ZMD206LoadType(t.enum8):
    """DP 4/10/18 load type."""

    led = 0
    incandescent = 1
    halogen = 2


class ZMD206PowerOnBehavior(t.enum8):
    """DP 14 behavior after a power interruption."""

    off = 0
    on = 1
    memory = 2


class ZMD206IndicatorStatus(t.enum8):
    """DP 21 indicator behavior."""

    off = 0
    follow_switch = 1
    position = 2


class ZMD206IndicatorColor(t.enum8):
    """DP 101/102 color index (shown as 1-9 in the vendor UI)."""

    color_1 = 0
    color_2 = 1
    color_3 = 2
    color_4 = 3
    color_5 = 4
    color_6 = 5
    color_7 = 6
    color_8 = 7
    color_9 = 8


class ZMD206ScreenOffTime(t.enum8):
    """DP 110 screen off delay."""

    never = 0
    seconds_10 = 1
    seconds_20 = 2
    seconds_30 = 3
    seconds_45 = 4
    seconds_60 = 5


class ZMD206LevelControl(NoManufacturerCluster, TuyaInWallLevelControl):
    """LevelControl without a Tuya manufacturer code requirement."""


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, int(value)))


def _raw_to_level(value: int) -> int:
    """Convert the device's 10..1000 DP range to ZCL 0..255."""
    raw = _clamp(value, BRIGHTNESS_MIN, BRIGHTNESS_MAX)
    return round((raw - BRIGHTNESS_MIN) * 255 / (BRIGHTNESS_MAX - BRIGHTNESS_MIN))


def _level_to_raw(value: int) -> int:
    """Convert ZCL 0..255 to the device's 10..1000 DP range."""
    level = _clamp(value, 0, 255)
    return round(BRIGHTNESS_MIN + level * (BRIGHTNESS_MAX - BRIGHTNESS_MIN) / 255)


def _raw_text_to_string(value) -> str:
    """Decode the raw Tuya string payload used by the panel name DPs."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\0")
    return str(value)


def _add_channel(builder: TuyaQuirkBuilder, channel: int) -> None:
    """Map one relay/brightness pair to a normal ZHA dimmable-light endpoint."""
    endpoint_id = channel
    base_dp = CHANNEL_DP_BASES[channel - 1]

    if endpoint_id != 1:
        builder.adds_endpoint(endpoint_id, device_type=zha.DeviceType.DIMMABLE_LIGHT)

    builder.adds(TuyaOnOffNM, endpoint_id=endpoint_id)
    builder.adds(ZMD206LevelControl, endpoint_id=endpoint_id)
    builder.tuya_dp(base_dp, TuyaOnOffNM.ep_attribute, "on_off", endpoint_id=endpoint_id)
    builder.tuya_dp(
        base_dp + 1,
        ZMD206LevelControl.ep_attribute,
        "current_level",
        converter=_raw_to_level,
        dp_converter=_level_to_raw,
        endpoint_id=endpoint_id,
    )


def _add_channel_settings(builder: TuyaQuirkBuilder, channel: int) -> None:
    """Add the vendor-confirmed per-channel configuration DPs."""
    base_dp = CHANNEL_DP_BASES[channel - 1]
    builder.tuya_number(
        dp_id=base_dp + 2,
        type=t.uint32_t,
        attribute_name=f"brightness_min_l{channel}",
        min_value=10,
        max_value=1000,
        step=1,
        translation_key=f"brightness_min_l{channel}",
        fallback_name=f"Channel {channel} minimum brightness",
    )
    builder.tuya_enum(
        dp_id=base_dp + 3,
        attribute_name=f"load_type_l{channel}",
        enum_class=ZMD206LoadType,
        translation_key=f"load_type_l{channel}",
        fallback_name=f"Channel {channel} load type",
    )
    builder.tuya_number(
        dp_id=base_dp + 4,
        type=t.uint32_t,
        attribute_name=f"brightness_max_l{channel}",
        min_value=10,
        max_value=1000,
        step=1,
        translation_key=f"brightness_max_l{channel}",
        fallback_name=f"Channel {channel} maximum brightness",
    )
    builder.tuya_number(
        dp_id=base_dp + 5,
        type=t.uint32_t,
        attribute_name=f"countdown_l{channel}",
        min_value=0,
        max_value=86400,
        step=1,
        unit="s",
        translation_key=f"countdown_l{channel}",
        fallback_name=f"Channel {channel} countdown",
    )


def _add_channel_name_cache(builder: TuyaQuirkBuilder, channel: int) -> None:
    """Accept name-hook DP reports without exposing a separate ZHA entity."""
    builder.tuya_dp_attribute(
        dp_id=105 + channel,
        attribute_name=f"screen_name_l{channel}",
        type=t.CharacterString,
        converter=_raw_text_to_string,
    )


def _register(manufacturer: str, channels: int) -> None:
    builder = (
        TuyaQuirkBuilder(manufacturer, "TS0601")
        .tuya_enchantment(data_query_spell=True)
        .replaces_endpoint(1, device_type=zha.DeviceType.DIMMABLE_LIGHT)
    )

    for channel in range(1, channels + 1):
        _add_channel(builder, channel)
        _add_channel_settings(builder, channel)
        _add_channel_name_cache(builder, channel)

    (
        builder.tuya_enum(
            dp_id=14,
            attribute_name="power_on_behavior",
            enum_class=ZMD206PowerOnBehavior,
            translation_key="power_on_behavior",
            fallback_name="Power-on behavior",
        )
        .tuya_enum(
            dp_id=21,
            attribute_name="indicator_status",
            enum_class=ZMD206IndicatorStatus,
            translation_key="indicator_status",
            fallback_name="Indicator behavior",
        )
        .tuya_switch(
            dp_id=26,
            attribute_name="backlight_switch",
            translation_key="backlight_switch",
            fallback_name="Screen backlight",
        )
        .tuya_enum(
            dp_id=101,
            attribute_name="indicator_color_on",
            enum_class=ZMD206IndicatorColor,
            translation_key="indicator_color_on",
            fallback_name="Indicator color while on",
        )
        .tuya_enum(
            dp_id=102,
            attribute_name="indicator_color_off",
            enum_class=ZMD206IndicatorColor,
            translation_key="indicator_color_off",
            fallback_name="Indicator color while off",
        )
        .tuya_number(
            dp_id=103,
            type=t.uint32_t,
            attribute_name="backlight_brightness",
            min_value=0,
            max_value=100,
            step=1,
            unit="%",
            translation_key="backlight_brightness",
            fallback_name="Screen backlight brightness",
        )
        .tuya_switch(
            dp_id=104,
            attribute_name="child_lock",
            translation_key="child_lock",
            fallback_name="Child lock",
        )
        .tuya_number(
            dp_id=105,
            type=t.uint32_t,
            attribute_name="gradient_rate",
            min_value=0,
            max_value=15,
            step=1,
            translation_key="gradient_rate",
            fallback_name="Dimming transition rate",
        )
        .tuya_enum(
            dp_id=110,
            attribute_name="screen_off_time",
            enum_class=ZMD206ScreenOffTime,
            translation_key="screen_off_time",
            fallback_name="Screen off delay",
        )
        .skip_configuration()
        .add_to_registry()
    )


_register("_TZE28C1000000_5aico93l", 1)
_register("_TZE284_5aico93l", 1)
_register("_TZE284_pyh4zt7w", 2)
_register("_TZE28C1000000_k9e7ihec", 3)
_register("_TZE284_k9e7ihec", 3)
