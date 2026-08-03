"""ZHA quirk for the Zemismart DN15-223F ultrasonic heat meter."""

import struct

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant import UnitOfElectricPotential
from zigpy.quirks.v2.homeassistant.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)
from zigpy.zcl.clusters.smartenergy import Metering

from zhaquirks.tuya.builder import TuyaQuirkBuilder, TuyaValveWaterConsumed
from zhaquirks.tuya.mcu import TuyaMCUCluster


class ReportPeriod(t.enum8):
    """Supported periodic report intervals."""

    Hour_1 = 0x00
    Hour_2 = 0x01
    Hour_3 = 0x02
    Hour_4 = 0x03
    Hour_6 = 0x04
    Hour_8 = 0x05
    Hour_12 = 0x06
    Hour_24 = 0x07
    Hour_48 = 0x08
    Hour_72 = 0x09


FAULTS = {
    1 << 0: "battery_alarm",
    1 << 1: "magnetism_alarm",
    1 << 2: "cover_alarm",
    1 << 3: "credit_alarm",
    1 << 4: "switch_gaps_alarm",
    1 << 5: "meter_body_alarm",
    1 << 6: "abnormal_water_alarm",
    1 << 7: "arrearage_alarm",
    1 << 8: "overflow_alarm",
    1 << 9: "revflow_alarm",
    1 << 10: "over_pre_alarm",
    1 << 11: "empty_pipe_alarm",
    1 << 12: "transducer_alarm",
}


def decode_uint32(value) -> int | None:
    """Decode the last four bytes of a Tuya raw datapoint."""

    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) < 4:
            return None
        return struct.unpack(">I", raw[-4:])[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def decode_raw_volume(value) -> float | None:
    """Decode an eight-byte period reply whose resolution is one litre."""

    if not isinstance(value, (bytes, bytearray, memoryview)) or len(value) != 8:
        return None
    decoded = decode_uint32(value)
    return None if decoded is None else decoded / 1000


def decode_hundredths(value) -> float | None:
    """Decode a Tuya value with two decimal places."""

    try:
        return int(value) / 100
    except (TypeError, ValueError):
        return None


def decode_faults(value) -> str:
    """Convert the DP5 bitmap to a readable fault list."""

    try:
        bitmap = int(value)
    except (TypeError, ValueError):
        return "invalid"
    if bitmap < 0:
        return "invalid"
    if bitmap == 0:
        return "OK"
    faults = [name for bit, name in FAULTS.items() if bitmap & bit]
    unknown_bits = bitmap & ~sum(FAULTS)
    if unknown_bits:
        faults.append(f"unknown_bits_0x{unknown_bits:X}")
    return ", ".join(faults)


def decode_meter_id(value) -> str | None:
    """Decode the meter's ASCII identifier."""

    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            decoded = bytes(value).decode("ascii").rstrip("\x00")
        except UnicodeDecodeError:
            return None
        return decoded or None
    if value is None:
        return None
    decoded = str(value).strip()
    return decoded or None


class HeatMeterWaterConsumed(TuyaValveWaterConsumed):
    """Metering cluster shared by cumulative and instantaneous water data."""

    _CONSTANT_ATTRIBUTES = {
        Metering.AttributeDefs.unit_of_measure.id: 0x01,
        Metering.AttributeDefs.multiplier.id: 1,
        Metering.AttributeDefs.divisor.id: 1000,
        Metering.AttributeDefs.summation_formatting.id: 0x33,
        Metering.AttributeDefs.demand_formatting.id: 0x2B,
        Metering.AttributeDefs.metering_device_type.id: 0x01,
    }


(
    TuyaQuirkBuilder("_TZE200_jt50ea5d", "TS0601")
    .friendly_name(model="DN15-223F", manufacturer="Zemismart")
    # DP1 is a value with two decimals. Multiplying by 10 lets the shared
    # Metering divisor (1000) expose it as cubic metres.
    .tuya_metering(dp_id=1, metering_cfg=HeatMeterWaterConsumed, scale=10)
    # DP2/DP3 are raw date-range replies. The final four bytes contain litres.
    .tuya_dp_attribute(
        dp_id=2,
        attribute_name="monthly_water_consumption",
        type=t.Single,
        converter=decode_raw_volume,
    )
    .sensor(
        attribute_name="monthly_water_consumption",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit="m³",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=3,
        unique_id_suffix="monthly_water_usage",
        fallback_name="Monthly Water Consumption",
    )
    .tuya_dp_attribute(
        dp_id=3,
        attribute_name="daily_water_consumption",
        type=t.Single,
        converter=decode_raw_volume,
    )
    .sensor(
        attribute_name="daily_water_consumption",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit="m³",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=3,
        unique_id_suffix="daily_water_usage",
        fallback_name="Daily Water Consumption",
    )
    .tuya_enum(
        dp_id=4,
        attribute_name="report_period",
        enum_class=ReportPeriod,
        translation_key="report_period",
        fallback_name="Report Period",
    )
    .tuya_sensor(
        dp_id=5,
        attribute_name="fault_status",
        type=t.CharacterString,
        converter=decode_faults,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="fault_status",
        fallback_name="Fault Status",
    )
    .tuya_switch(
        dp_id=7,
        attribute_name="heat_metering_enabled",
        translation_key="heat_metering",
        fallback_name="Heat Metering",
    )
    .tuya_dp_attribute(
        dp_id=8,
        attribute_name="cumulative_heat",
        type=t.Single,
        converter=decode_hundredths,
    )
    .sensor(
        attribute_name="cumulative_heat",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit="kWh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        unique_id_suffix="heat_energy_total",
        fallback_name="Cumulative Heat",
    )
    .tuya_sensor(
        dp_id=16,
        attribute_name="meter_id",
        type=t.CharacterString,
        converter=decode_meter_id,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="meter_id",
        fallback_name="Meter ID",
    )
    .tuya_dp(
        dp_id=19,
        ep_attribute=HeatMeterWaterConsumed.ep_attribute,
        attribute_name=Metering.AttributeDefs.instantaneous_demand.name,
        converter=decode_uint32,
    )
    .tuya_dp_attribute(
        dp_id=21,
        attribute_name="inlet_water_temperature",
        type=t.Single,
        converter=decode_hundredths,
    )
    .sensor(
        attribute_name="inlet_water_temperature",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        unique_id_suffix="temperature_in",
        fallback_name="Inlet Water Temperature",
    )
    .tuya_dp_attribute(
        dp_id=22,
        attribute_name="outlet_water_temperature",
        type=t.Single,
        converter=decode_hundredths,
    )
    .sensor(
        attribute_name="outlet_water_temperature",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        unique_id_suffix="temperature_out",
        fallback_name="Outlet Water Temperature",
    )
    .tuya_dp_attribute(
        dp_id=24,
        attribute_name="supply_voltage",
        type=t.Single,
        converter=decode_hundredths,
    )
    .sensor(
        attribute_name="supply_voltage",
        cluster_id=TuyaMCUCluster.cluster_id,
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        unique_id_suffix="voltage",
        fallback_name="Supply Voltage",
    )
    .skip_configuration()
    .add_to_registry()
)
