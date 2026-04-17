"""Custom ZHA quirk for Zemismart/Tuya TS0601 chain curtain motor."""

from __future__ import annotations

from zigpy.profiles import zha
from zigpy.zcl.clusters.general import Basic, Groups, Ota, Scenes, Time

from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya import (
    TuyaManufacturerWindowCover,
    TuyaManufCluster,
    TuyaWindowCover,
    TuyaWindowCoverControl,
)

try:
    import zigpy.types as t
    from zhaquirks.tuya.builder import TuyaQuirkBuilder

    _BUILDER_OK = True
except Exception:
    _BUILDER_OK = False


if _BUILDER_OK:
    class MotorDirection(t.enum8):
        """Motor direction for the curtain motor."""

        forward = 0x00
        back = 0x01


    class LimitAction(t.enum8):
        """Limit configuration actions exposed by the Tuya MCU."""

        set_upper_limit = 0x00
        set_lower_limit = 0x01
        delete_upper_limit = 0x02
        delete_lower_limit = 0x03
        delete_all_limits = 0x04


    (
        TuyaQuirkBuilder("_TZE284_6hrnp30w", "TS0601")
        .tuya_cover(control_dp=1, position_state_dp=3, position_control_dp=2, invert=True)
        .tuya_battery(dp_id=13)
        .tuya_enum(
            dp_id=5,
            attribute_name="motor_direction",
            enum_class=MotorDirection,
            translation_key="motor_direction",
            fallback_name="Motor direction",
        )
        .tuya_enum(
            dp_id=16,
            attribute_name="limit_action",
            enum_class=LimitAction,
            translation_key="limit_action",
            fallback_name="Limit action",
        )
        .skip_configuration()
        .add_to_registry()
    )
else:
    class ZemismartTs0601Cover(TuyaWindowCover):
        """Fallback quirk when the Tuya builder API is unavailable."""

        signature = {
            MODELS_INFO: [
                ("_TZE284_6hrnp30w", "TS0601"),
            ],
            ENDPOINTS: {
                1: {
                    PROFILE_ID: zha.PROFILE_ID,
                    DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                    INPUT_CLUSTERS: [
                        Basic.cluster_id,
                        Groups.cluster_id,
                        Scenes.cluster_id,
                        0xED00,
                        TuyaManufCluster.cluster_id,
                    ],
                    OUTPUT_CLUSTERS: [
                        Time.cluster_id,
                        Ota.cluster_id,
                    ],
                }
            },
        }

        replacement = {
            ENDPOINTS: {
                1: {
                    PROFILE_ID: zha.PROFILE_ID,
                    DEVICE_TYPE: zha.DeviceType.WINDOW_COVERING_DEVICE,
                    INPUT_CLUSTERS: [
                        Basic.cluster_id,
                        Groups.cluster_id,
                        Scenes.cluster_id,
                        TuyaManufacturerWindowCover,
                        TuyaWindowCoverControl,
                    ],
                    OUTPUT_CLUSTERS: [
                        Ota.cluster_id,
                    ],
                }
            },
        }
