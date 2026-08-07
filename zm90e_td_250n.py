"""ZHA quirk for the Zemismart ZM90E-TD-250N Zigbee window opener.

Supported fingerprint:
* TS0601 / _TZE284_fzo2pocs

Tuya datapoints:
* DP 1: open / stop / close
* DP 2: target position
* DP 3: arrived position
* DP 5: motor direction
* DP 103 / 104 / 105: open / middle / close limit actions
* DP 106: motor working mode
"""

from __future__ import annotations

import zigpy.types as t
from zha.application import EntityType
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Ota

from zhaquirks.tuya import TuyaWindowCoverControl
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class ZM90EMotorDirection(t.enum8):
    """DP 5 motor direction."""

    normal = 0x00
    reversed = 0x01


class ZM90EMotorWorkingMode(t.enum8):
    """DP 106 motor working mode."""

    continuous = 0x00
    intermittent = 0x01


(
    TuyaQuirkBuilder("_TZE284_fzo2pocs", "TS0601")
    .friendly_name(manufacturer="Zemismart", model="ZM90E-TD-250N")
    .tuya_enchantment(data_query_spell=True)
    .tuya_cover(control_dp=1, position_state_dp=3, position_control_dp=2)
    .tuya_enum(
        dp_id=5,
        attribute_name="motor_direction",
        enum_class=ZM90EMotorDirection,
        translation_key="motor_direction",
        fallback_name="Motor direction",
    )
    .tuya_dp_attribute(
        dp_id=103,
        attribute_name="open_limit",
        type=t.Bool,
        access=foundation.ZCLAttributeAccess.Write,
    )
    .write_attr_button(
        attribute_name="open_limit",
        attribute_value=True,
        cluster_id=0xEF00,
        unique_id_suffix="set_open_limit",
        translation_key="set_open_limit",
        fallback_name="Set open limit",
        entity_type=EntityType.STANDARD,
    )
    .write_attr_button(
        attribute_name="open_limit",
        attribute_value=False,
        cluster_id=0xEF00,
        unique_id_suffix="reset_open_limit",
        translation_key="reset_open_limit",
        fallback_name="Reset open limit",
        entity_type=EntityType.STANDARD,
    )
    .tuya_dp_attribute(
        dp_id=104,
        attribute_name="middle_limit",
        type=t.Bool,
        access=foundation.ZCLAttributeAccess.Write,
    )
    .write_attr_button(
        attribute_name="middle_limit",
        attribute_value=True,
        cluster_id=0xEF00,
        unique_id_suffix="set_middle_limit",
        translation_key="set_middle_limit",
        fallback_name="Set middle limit",
        entity_type=EntityType.STANDARD,
    )
    .write_attr_button(
        attribute_name="middle_limit",
        attribute_value=False,
        cluster_id=0xEF00,
        unique_id_suffix="reset_middle_limit",
        translation_key="reset_middle_limit",
        fallback_name="Reset middle limit",
        entity_type=EntityType.STANDARD,
    )
    .tuya_dp_attribute(
        dp_id=105,
        attribute_name="close_limit",
        type=t.Bool,
        access=foundation.ZCLAttributeAccess.Write,
    )
    .write_attr_button(
        attribute_name="close_limit",
        attribute_value=True,
        cluster_id=0xEF00,
        unique_id_suffix="set_close_limit",
        translation_key="set_close_limit",
        fallback_name="Set close limit",
        entity_type=EntityType.STANDARD,
    )
    .write_attr_button(
        attribute_name="close_limit",
        attribute_value=False,
        cluster_id=0xEF00,
        unique_id_suffix="reset_close_limit",
        translation_key="reset_close_limit",
        fallback_name="Reset close limit",
        entity_type=EntityType.STANDARD,
    )
    .tuya_enum(
        dp_id=106,
        attribute_name="motor_working_mode",
        enum_class=ZM90EMotorWorkingMode,
        translation_key="motor_working_mode",
        fallback_name="Motor working mode",
    )
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=TuyaWindowCoverControl.cluster_id,
        unique_id_suffix="1-258-window_covering_type",
    )
    .prevent_default_entity_creation(
        endpoint_id=1,
        cluster_id=Ota.cluster_id,
        unique_id_suffix="1-25-firmware_update",
    )
    .skip_configuration()
    .add_to_registry()
)
