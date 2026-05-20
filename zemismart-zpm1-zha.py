"""Zemismart ZMP1 Roller Shade Driver - ZHA Custom Quirk.

TS0601 / _TZE284_6hrnp30w

Pure v2. Place in /config/custom_zha_quirks/zemismart_zmp1.py
"""

from __future__ import annotations

import zigpy.types as t
from zigpy.quirks.v2 import CustomDeviceV2, EntityType, EntityPlatform

from zigpy.zcl import foundation
from zhaquirks.tuya.mcu import TuyaMCUCluster, TuyaWindowCovering
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class ZMP1ManufCluster(TuyaMCUCluster):
    """TuyaMCUCluster subclass — no dp_to_attribute here.
    The builder populates _dp_to_attributes via tuya_cover()/tuya_enum().
    Limit and nudge methods send raw Tuya commands directly.
    """

    def _send_dp_enum(self, dp_id: int, value: int) -> None:
        from zhaquirks.tuya import TUYA_SET_DATA, TuyaManufCluster
        cmd_payload = TuyaManufCluster.Command()
        cmd_payload.status     = 0
        cmd_payload.tsn        = self.endpoint.device.application.get_sequence()
        cmd_payload.command_id = 0x0400 | dp_id
        cmd_payload.function   = 0
        cmd_payload.data       = t.List[t.uint8_t]([1, value])
        self.create_catching_task(
            self.command(TUYA_SET_DATA, cmd_payload, expect_reply=False)
        )

    def set_upper_limit(self)    -> None: self._send_dp_enum(0x10, 0x00)
    def set_lower_limit(self)    -> None: self._send_dp_enum(0x10, 0x01)
    def remove_upper_limit(self) -> None: self._send_dp_enum(0x10, 0x02)
    def remove_lower_limit(self) -> None: self._send_dp_enum(0x10, 0x03)
    def clear_limits(self)       -> None: self._send_dp_enum(0x10, 0x04)
    def click_up(self)           -> None: self._send_dp_enum(0x14, 0x00)
    def click_down(self)         -> None: self._send_dp_enum(0x14, 0x01)


class ZMP1DeviceV2(CustomDeviceV2):
    """CustomDeviceV2 — TuyaMCUCluster.__init__ creates command_bus automatically."""
    pass


class MotorDirectionEnum(t.enum8):
    Forward = 0x00
    Back    = 0x01


class WorkStateEnum(t.enum8):
    Opening = 0x00
    Closing = 0x01


class MotorLimitsEnum(t.enum8):
    Set_upper_limit    = 0x00
    Set_lower_limit    = 0x01
    Remove_upper_limit = 0x02
    Remove_lower_limit = 0x03
    Clear_both_limits  = 0x04


class ClickControlEnum(t.enum8):
    Up   = 0x00
    Down = 0x01


(
    TuyaQuirkBuilder("_TZE284_6hrnp30w", "TS0601")
    .device_class(ZMP1DeviceV2)
    # tuya_cover() maps DP1->control, DP3->position state, DP2->position setpoint
    # adds TuyaWindowCovering and sets endpoint device_type to WINDOW_COVERING_DEVICE
    .tuya_cover(
        control_dp=1,
        position_state_dp=3,
        position_control_dp=2,
        invert=False,
    )
    .tuya_enum(
        dp_id=16,
        attribute_name="motor_limits",
        enum_class=MotorLimitsEnum,
        translation_key="motor_limits",
        fallback_name="Motor Limits",
        entity_type=EntityType.CONFIG,
        entity_platform=EntityPlatform.SELECT,
    )
    .tuya_dp_attribute(
        dp_id=20,
        attribute_name="click_up",
        type=ClickControlEnum,
    )
    .write_attr_button(
        attribute_name="click_up",
        attribute_value=0x00,
        cluster_id=0xEF00,
        translation_key="click_up",
        fallback_name="Nudge Up",
        entity_type=EntityType.STANDARD,
    )
    .tuya_attribute(
        dp_id=20,
        attribute_name="click_down",
        type=ClickControlEnum,
    )
    .write_attr_button(
        attribute_name="click_down",
        attribute_value=0x01,
        cluster_id=0xEF00,
        translation_key="click_down",
        fallback_name="Nudge Down",
        entity_type=EntityType.STANDARD,
    )
    # DP5 — motor direction
    .tuya_enum(
        dp_id=5,
        attribute_name="motor_direction",
        enum_class=MotorDirectionEnum,
        translation_key="motor_direction",
        fallback_name="Motor Direction",
        entity_type=EntityType.CONFIG,
        entity_platform=EntityPlatform.SELECT,
    )
    # DP7 — work state (opening/closing), read-only sensor
    .tuya_dp_attribute(
        dp_id=7,
        attribute_name="work_state",
        type=t.CharacterString,
        converter=lambda x: WorkStateEnum(x).name,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .sensor(
        attribute_name="work_state",
        cluster_id=0xEF00,
        translation_key="work_state",
        fallback_name="Work State",
        entity_type=EntityType.DIAGNOSTIC,
    )
    # DP10 — calibrated travel time in ms, read-only sensor
    .tuya_dp_attribute(
        dp_id=10,
        attribute_name="time_total",
        type=t.uint32_t,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .sensor(
        attribute_name="time_total",
        cluster_id=0xEF00,
        translation_key="time_total",
        fallback_name="Travel Time",
        entity_type=EntityType.DIAGNOSTIC,
    )
    # DP12 — motor fault bitmap, read-only sensor
    .tuya_dp_attribute(
        dp_id=12,
        attribute_name="motor_fault",
        type=t.uint8_t,
        access=foundation.ZCLAttributeAccess.Read,
    )
    .sensor(
        attribute_name="motor_fault",
        cluster_id=0xEF00,
        translation_key="motor_fault",
        fallback_name="Motor Fault",
        entity_type=EntityType.DIAGNOSTIC,
    )
    # DP13 — battery percentage
    .tuya_battery(dp_id=13)
    .skip_configuration()
    .add_to_registry(replacement_cluster=ZMP1ManufCluster)
)