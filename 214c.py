"""Collection of Tuya Valve devices e.g. water valves, gas valve etc."""
import struct
from datetime import datetime, timedelta, timezone

from zigpy.quirks.v2 import BinarySensorDeviceClass, EntityPlatform, EntityType
from zigpy.quirks.v2.homeassistant import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfTime,
    UnitOfVolume,
)
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
import zigpy.types as t
from zigpy.zcl.clusters.smartenergy import Metering

from zhaquirks.const import BatterySize
from zhaquirks.tuya import TUYA_CLUSTER_ID, TUYA_SEND_DATA
from zhaquirks.tuya.builder import TuyaQuirkBuilder, TuyaValveWaterConsumed
from zhaquirks.tuya.mcu import TuyaMCUCluster

class CustomTuyaValveWaterConsumed(TuyaValveWaterConsumed):
    _CONSTANT_ATTRIBUTES = {
        # 0x0300: 计量单位（立方米）
        0x0300: 0x0001,  # 标准枚举值：0x0001 = 立方米（m³）
        # 0x0301: 乘数（根据设备原始值调整）
        0x0301: 1,       # 若设备原始值为m³，乘数=1
        # 0x0302: 除数（根据设备原始值调整）
        0x0302: 1000,       # 若设备原始值为m³，除数=1
        # 0x0303: 累计值格式（整数3位+小数3位，适合m³）
        0x0303: 0x33,    # bit4-7=1（小数3位），bit0-3=3（整数3位）
        # 0x0304: 瞬时需求格式（整数2位+小数3位，适合m³/h）
        0x0304: 0x1C,    # bit4-7=1（小数3位），bit0-3=2（整数2位）
        # 0x0306: 设备类型（水表）
        0x0306: 0x01,    # 标准枚举值：0x01 = 水计量设备
    }

# Tuya 214C Ultrasonic water meter valve
(
    TuyaQuirkBuilder("_TZE284_vuwtqx0t", "TS0601")
    # 关键修改：使用自定义的CustomTuyaValveWaterConsumed替代默认配置
    .tuya_metering(dp_id=1, metering_cfg=CustomTuyaValveWaterConsumed)
    # Skipped DP 2,3,4,5,6,16,18
    .tuya_onoff(dp_id=13)
    .tuya_switch(
        dp_id=14,
        attribute_name="auto_clean",
        entity_type=EntityType.CONFIG,
        translation_key="auto_clean",
        fallback_name="Auto clean",
    )
    .tuya_dp(
        dp_id=21,
        ep_attribute=CustomTuyaValveWaterConsumed.ep_attribute,  # 对应自定义计量配置
        attribute_name=Metering.AttributeDefs.instantaneous_demand.name,
        # 确保转换后的值与multiplier/divisor匹配（例如：若原始值是分升，转换后直接用整数）
        converter=lambda x: struct.unpack(">I", x[-4:])[0] if isinstance(x, bytes) and len(x) >= 4 else x,
    )
    .tuya_temperature(
        dp_id=22,
        scale=1
    )
    .tuya_sensor(
        dp_id=26,
        attribute_name="voltage",
        type=t.uint16_t,
        converter=lambda x: x / 100,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        entity_type=EntityType.STANDARD,
        fallback_name="Voltage",
    )
    .skip_configuration()
    .add_to_registry()
)