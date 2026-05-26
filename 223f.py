"""Collection of Tuya Valve devices e.g. water valves, gas valve etc."""
import struct

import zigpy.types as t
from zigpy.zcl.clusters.smartenergy import Metering

from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant import UnitOfElectricPotential
from zigpy.quirks.v2.homeassistant.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from zhaquirks.tuya.builder import TuyaQuirkBuilder, TuyaValveWaterConsumed


# ===========================
# 水量计量配置（Metering）
# ===========================
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

# ===========================
# ===========================
(
    TuyaQuirkBuilder("_TZE200_jt50ea5d", "TS0601")

    # ---------------------------
    # 累计水量 DP1（Metering）
    # ---------------------------
    .tuya_metering(dp_id=1, metering_cfg=CustomTuyaValveWaterConsumed)

    # ---------------------------
    # 瞬时流量 DP19（绑定水量 Metering）
    # ---------------------------
      .tuya_dp(
        dp_id=19,
        ep_attribute=CustomTuyaValveWaterConsumed.ep_attribute,  # 对应自定义计量配置
        attribute_name=Metering.AttributeDefs.instantaneous_demand.name,
        # 确保转换后的值与multiplier/divisor匹配（例如：若原始值是分升，转换后直接用整数）
        converter=lambda x: struct.unpack(">I", x[-4:])[0] if isinstance(x, bytes) and len(x) >= 4 else x,
    )

    # ---------------------------
    # 累计热量 DP8（Sensor，单位 kWh）
    # ---------------------------
    .tuya_sensor(
        dp_id=8,
        attribute_name="heat_energy_total",
        type=t.uint32_t,
        converter=lambda x: struct.unpack(">I", x[-4:])[0] if isinstance(x, bytes) and len(x) >= 4 else x,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit="kWh",
        entity_type=EntityType.STANDARD,
        fallback_name="Total Heat Energy",
    )

    # ---------------------------
    # 温度传感器 1（进水 DP21）
    # ---------------------------
    .tuya_sensor(
        dp_id=21,
        attribute_name="temperature_in",
        type=t.int16s,
        converter=lambda x: x / 100,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit="°C",
        entity_type=EntityType.STANDARD,
        fallback_name="Inlet Temperature",
    )

    # ---------------------------
    # 温度传感器 2（出水 DP22）
    # ---------------------------
    .tuya_sensor(
        dp_id=22,
        attribute_name="temperature_out",
        type=t.int16s,
        converter=lambda x: x / 100,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        unit="°C",
        entity_type=EntityType.STANDARD,
        fallback_name="Outlet Temperature",
    )

    # ---------------------------
    # 电压 DP24
    # ---------------------------
    .tuya_sensor(
        dp_id=24,
        attribute_name="voltage",
        type=t.int16s,
        converter=lambda x: x / 100,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        entity_type=EntityType.STANDARD,
        fallback_name="Voltage",
    )

    .tuya_sensor(
        dp_id=2,  
        attribute_name="daily_water_usage",
        type=t.uint32_t,
        converter=lambda x: struct.unpack(">I", x[-4:])[0] if isinstance(x, bytes) and len(x) >= 4 else x,
        unit="m³",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_type=EntityType.STANDARD,
        fallback_name="Daily Water Usage",
    )

    .tuya_sensor(
        dp_id=3,
        attribute_name="monthly_water_usage",
        type=t.uint32_t,
        converter=lambda x: struct.unpack(">I", x[-4:])[0] if isinstance(x, bytes) and len(x) >= 4 else x,
        unit="m³",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_type=EntityType.STANDARD,
        fallback_name="Monthly Water Usage",
    )

    .skip_configuration()
    .add_to_registry()
)
