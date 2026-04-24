"""Custom ZHA quirk for Zemismart ZM25Z (_TZE200_cirjrpxe / TS0301).

Based on vendor DP definition:
- DP1: control
- DP2: percent_control
- DP3: percent_state
- DP5: control_back
- DP118: limit_set_del
- DP120: limit_set_switch
"""

import zigpy.types as t

from zhaquirks.tuya.builder import TuyaQuirkBuilder


class MotorDirection(t.enum8):
    """Motor direction values for DP5."""

    Forward = 0x00
    Back = 0x01


class LimitAction(t.enum8):
    """Limit set/delete action values for DP118."""

    LimitDeleteUp = 0x00
    LimitDeleteDown = 0x01
    LimitDeleteFavorite = 0x02
    LimitSetUp = 0x03
    LimitSetDown = 0x04
    LimitSetFavorite = 0x05


(
    TuyaQuirkBuilder("_TZE200_cirjrpxe", "TS0301")
    .tuya_cover(
        control_dp=1,
        position_state_dp=3,
        position_control_dp=2,
        invert=False,
    )
    .tuya_enum(
        dp_id=5,
        attribute_name="motor_direction",
        enum_class=MotorDirection,
        translation_key="motor_direction",
        fallback_name="Motor direction",
    )
    .tuya_enum(
        dp_id=118,
        attribute_name="limit_action",
        enum_class=LimitAction,
        translation_key="limit_action",
        fallback_name="Limit action",
    )
    .prevent_default_entity_creation(endpoint_id=1, cluster_id=0x0001)
    .skip_configuration()
    .add_to_registry()
)
