"""ZHA quirk for the Zemismart ZW-EU-02-PS two-channel metering relay."""

from zha.application import EntityType
from zha.application.platforms.number.device_class import NumberDeviceClass
from zha.application.platforms.sensor.device_class import (
    SensorDeviceClass,
    SensorStateClass,
)
from zha.units import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTime,
)
import zigpy.types as t

from zhaquirks.tuya.builder import TuyaQuirkBuilder

(
    TuyaQuirkBuilder("_TZE284_qgtqlkhm", "TS0601")
    .friendly_name(manufacturer="Zemismart", model="ZW-EU-02-PS")
    .tuya_switch(
        dp_id=1,
        attribute_name="relay_l1",
        entity_type=EntityType.STANDARD,
        translation_key="relay_l1",
        fallback_name="L1",
    )
    .tuya_switch(
        dp_id=2,
        attribute_name="relay_l2",
        entity_type=EntityType.STANDARD,
        translation_key="relay_l2",
        fallback_name="L2",
    )
    .tuya_switch(
        dp_id=13,
        attribute_name="master_switch",
        entity_type=EntityType.STANDARD,
        translation_key="master_switch",
        fallback_name="Master switch",
    )
    .tuya_number(
        dp_id=7,
        attribute_name="countdown_l1",
        type=t.uint32_t,
        min_value=0,
        max_value=43200,
        step=1,
        device_class=NumberDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        translation_key="countdown_l1",
        fallback_name="L1 countdown",
    )
    .tuya_number(
        dp_id=8,
        attribute_name="countdown_l2",
        type=t.uint32_t,
        min_value=0,
        max_value=43200,
        step=1,
        device_class=NumberDeviceClass.DURATION,
        unit=UnitOfTime.SECONDS,
        translation_key="countdown_l2",
        fallback_name="L2 countdown",
    )
    .tuya_sensor(
        dp_id=21,
        attribute_name="current",
        type=t.uint32_t,
        divisor=1000,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricCurrent.AMPERE,
        fallback_name="Current",
    )
    .tuya_sensor(
        dp_id=22,
        attribute_name="power",
        type=t.uint32_t,
        divisor=10,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfPower.WATT,
        fallback_name="Power",
    )
    .tuya_sensor(
        dp_id=23,
        attribute_name="voltage",
        type=t.uint32_t,
        divisor=10,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit=UnitOfElectricPotential.VOLT,
        fallback_name="Voltage",
    )
    .skip_configuration()
    .tuya_enchantment(data_query_spell=True)
    .add_to_registry()
)
