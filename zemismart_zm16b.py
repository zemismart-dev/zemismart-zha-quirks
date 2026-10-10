# SPDX-License-Identifier: Apache-2.0
# Adapted from zigpy/zha-device-handlers, zhaquirks/tuya/ts0601_cover.py
# Revision: d6fcec59eff9f63f154723500be9378be926d927 (ZM16B definition).
"""ZHA support for the new Zemismart ZM16B manufacturer fingerprint.

Match only TS0601 / _TZE2841000000_3mzb0sdz. The older
_TZE284_3mzb0sdz retains its built-in ZHA quirk. Datapoints and entity
identifiers follow the built-in ZM16B definition without changes.
"""

import zigpy.types as t

from zhaquirks.tuya import TUYA_CLUSTER_ID
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class MotorDirection(t.enum8):
    """Motor direction values."""

    Forward = 0x00
    Back = 0x01


class BorderSetting(t.enum8):
    """Border/limit setting values."""

    Up = 0x00
    Down = 0x01
    Up_delete = 0x02
    Down_delete = 0x03
    Remove_top_bottom = 0x04


(
    TuyaQuirkBuilder("_TZE2841000000_3mzb0sdz", "TS0601")
    .tuya_cover(control_dp=1, position_state_dp=8, position_control_dp=9)
    .tuya_battery(dp_id=13)
    .tuya_enum(
        dp_id=11,
        attribute_name="motor_direction",
        enum_class=MotorDirection,
        translation_key="motor_direction",
        fallback_name="Motor direction",
    )
    .tuya_dp_attribute(
        dp_id=16,
        attribute_name="border",
        type=BorderSetting,
    )
    .write_attr_button(
        attribute_name="border",
        attribute_value=BorderSetting.Up,
        cluster_id=TUYA_CLUSTER_ID,
        unique_id_suffix="border_up",
        translation_key="set_upper_limit",
        fallback_name="Set upper limit",
    )
    .write_attr_button(
        attribute_name="border",
        attribute_value=BorderSetting.Down,
        cluster_id=TUYA_CLUSTER_ID,
        unique_id_suffix="border_down",
        translation_key="set_lower_limit",
        fallback_name="Set lower limit",
    )
    .write_attr_button(
        attribute_name="border",
        attribute_value=BorderSetting.Up_delete,
        cluster_id=TUYA_CLUSTER_ID,
        unique_id_suffix="border_up_delete",
        translation_key="delete_upper_limit",
        fallback_name="Delete upper limit",
    )
    .write_attr_button(
        attribute_name="border",
        attribute_value=BorderSetting.Down_delete,
        cluster_id=TUYA_CLUSTER_ID,
        unique_id_suffix="border_down_delete",
        translation_key="delete_lower_limit",
        fallback_name="Delete lower limit",
    )
    .write_attr_button(
        attribute_name="border",
        attribute_value=BorderSetting.Remove_top_bottom,
        cluster_id=TUYA_CLUSTER_ID,
        unique_id_suffix="border_remove_all",
        translation_key="delete_all_limits",
        fallback_name="Delete all limits",
    )
    .skip_configuration()
    .add_to_registry()
)
