"""ZHA quirk for the Zemismart ZM90E-TD-250N Zigbee window opener.

Supported fingerprint:
* TS0601 / _TZE284_fzo2pocs

Tuya datapoints:
* DP 1: open / stop / close
* DP 2: target position
* DP 3: arrived position
* DP 5: motor direction
* DP 106: motor working mode
"""

from __future__ import annotations

import zigpy.types as t
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
