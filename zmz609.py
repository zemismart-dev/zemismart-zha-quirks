"""Stable ZHA quirk for the Tuya TS0601 2/3-gang wall switch panel.

This version keeps the classic Tuya MCU switch mapping that already works for
the relays, then adds a conservative set of extra writable datapoints from
the vendor DP sheet. Where the vendor model uses enums or booleans, we expose
the raw values first because that is the most compatible option with older ZHA
quirk APIs.
"""

from __future__ import annotations

import enum
from typing import Final

import zigpy.types as t
from zigpy.profiles import zgp, zha
from zigpy.zcl.foundation import ZCLAttributeDef
from zigpy.zcl.clusters.general import (
    AnalogInput,
    AnalogOutput,
    Basic,
    BinaryOutput,
    GreenPowerProxy,
    Groups,
    Identify,
    OnOff,
    Ota,
    Scenes,
    Time,
)

from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.quirk_ids import TUYA_PLUG_ONOFF
from zhaquirks.tuya import (
    TuyaData,
    TuyaLocalCluster,
    TuyaSwitch,
    TuyaZBElectricalMeasurement,
    TuyaZBMeteringClusterWithUnit,
)
from zhaquirks.tuya.mcu import (
    DPToAttributeMapping,
    MoesSwitchManufCluster,
    TuyaAttributesCluster,
    TuyaOnOffNM,
)


class TuyaEnum(enum.IntEnum):
    """Generic enum value used for Tuya enum DPs exposed as AnalogOutput."""

    option_0 = 0
    option_1 = 1
    option_2 = 2
    option_3 = 3
    option_4 = 4
    option_5 = 5


def _tuya_enum(value) -> TuyaEnum:
    """Convert a visible numeric enum value into a Tuya ENUM payload."""

    return TuyaEnum(int(round(float(value))))


class PowerOnState(t.enum8):
    """Tuya power-on behavior enum used by ZHA select entities."""

    Off = 0x00
    On = 0x01
    LastState = 0x02


def _power_on_state(value) -> PowerOnState:
    """Convert Tuya/ZHA enum values into a stable power-on enum payload."""

    return PowerOnState(int(value))


def _decode_dp_string(value) -> str:
    """Decode Tuya raw/string DPs into text."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _encode_dp_string(value) -> "RawBytes":
    """Encode HA text in the raw string format used by screen-name DPs."""

    return RawBytes(str(value).encode("utf-8"))


def _attribute_ids(attribute_defs, *names: str) -> set[int]:
    """Return attribute ids that exist in the current zigpy/zhaquirks version."""

    return {
        getattr(attribute_defs, name).id
        for name in names
        if hasattr(attribute_defs, name)
    }


class TuyaConfigNumber(TuyaAttributesCluster, AnalogOutput):
    """Base AnalogOutput cluster used to expose Tuya writable number settings."""

    dp_id: int | None = None

    _CONSTANT_ATTRIBUTES = {
        AnalogOutput.AttributeDefs.out_of_service.id: 0,
        AnalogOutput.AttributeDefs.status_flags.id: 0,
    }

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Normalize visible number values, then let TuyaAttributesCluster send the DP."""

        present_value_id = self.attributes_by_name["present_value"].id
        normalized = {}

        for attrid, value in attributes.items():
            resolved_attrid = (
                self.attributes_by_name[attrid].id
                if isinstance(attrid, str)
                else getattr(attrid, "id", attrid)
            )
            if resolved_attrid == present_value_id:
                value = int(round(float(value)))
            normalized[attrid] = value

        return await super().write_attributes(
            normalized, manufacturer=manufacturer, **kwargs
        )


class TuyaConfigSwitch(TuyaAttributesCluster, BinaryOutput):
    """Base BinaryOutput cluster used to expose Tuya writable boolean settings."""

    dp_id: int | None = None

    _CONSTANT_ATTRIBUTES = {
        BinaryOutput.AttributeDefs.out_of_service.id: 0,
        BinaryOutput.AttributeDefs.status_flags.id: 0,
    }

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Normalize visible boolean state, then let TuyaAttributesCluster send the DP."""

        present_value_id = self.attributes_by_name["present_value"].id
        normalized = {}

        for attrid, value in attributes.items():
            resolved_attrid = (
                self.attributes_by_name[attrid].id
                if isinstance(attrid, str)
                else getattr(attrid, "id", attrid)
            )
            if resolved_attrid == present_value_id:
                value = bool(value)
            normalized[attrid] = value

        return await super().write_attributes(
            normalized, manufacturer=manufacturer, **kwargs
        )


class O409r73pRelayOnOffCluster(TuyaAttributesCluster, TuyaOnOffNM):
    """Relay OnOff cluster with Tuya power-on behavior and panel name attributes."""

    class AttributeDefs(TuyaOnOffNM.AttributeDefs):
        """Cluster attributes."""

        power_on_state: Final = ZCLAttributeDef(id=0x8002, type=PowerOnState)
        name_update_1: Final = ZCLAttributeDef(id=0x8003, type=t.CharacterString)
        name_update_2: Final = ZCLAttributeDef(id=0x8004, type=t.CharacterString)
        name_update_3: Final = ZCLAttributeDef(id=0x8005, type=t.CharacterString)

    _CONSTANT_ATTRIBUTES = {
        **getattr(TuyaOnOffNM, "_CONSTANT_ATTRIBUTES", {}),
        AttributeDefs.power_on_state.id: PowerOnState.LastState,
    }

    async def write_attributes(self, attributes, manufacturer=None, **kwargs):
        """Normalize power-on enum writes, then let TuyaAttributesCluster send the DP."""

        power_on_state_id = self.attributes_by_name["power_on_state"].id
        normalized = {}

        for attrid, value in attributes.items():
            resolved_attrid = (
                self.attributes_by_name[attrid].id
                if isinstance(attrid, str)
                else getattr(attrid, "id", attrid)
            )
            if resolved_attrid == power_on_state_id:
                value = _power_on_state(value)
            normalized[attrid] = value

        return await super().write_attributes(
            normalized, manufacturer=manufacturer, **kwargs
        )


class RawBytes(TuyaData):
    """Helper for Tuya string DPs."""

    def __init__(self, value: bytes):
        self.raw = value

    def serialize(self) -> bytes:
        length = len(self.raw)
        return b"\x00" + length.to_bytes(2, "big") + self.raw

    def __repr__(self):
        return f"<RawBytes {self.raw!r}>"


def _name_dp_mapping(attribute_name: str, endpoint_id: int = 1) -> DPToAttributeMapping:
    """Map a screen name DP to the Tuya MCU attribute used by zha_namehook."""

    return DPToAttributeMapping(
        ep_attribute="tuya_mcu",
        attribute_name=attribute_name,
        converter=_decode_dp_string,
        dp_converter=_encode_dp_string,
        endpoint_id=endpoint_id,
    )


class O409r73pElectricalMeasurement(TuyaLocalCluster, TuyaZBElectricalMeasurement):
    """Standard ZHA electrical measurement values from vendor DPs 21-23."""

    _SUPPORTED_ATTRIBUTES = _attribute_ids(
        TuyaZBElectricalMeasurement.AttributeDefs,
        "active_power",
        "rms_current",
        "rms_voltage",
    )
    _UNSUPPORTED_ATTRIBUTES = _attribute_ids(
        TuyaZBElectricalMeasurement.AttributeDefs,
        "ac_frequency",
        "active_power_ph_b",
        "active_power_ph_c",
        "apparent_power",
        "power_factor",
        "rms_current_ph_b",
        "rms_current_ph_c",
        "rms_voltage_ph_b",
        "rms_voltage_ph_c",
        "total_active_power",
    )

    def is_attribute_unsupported(self, attr):
        """Keep only the vendor-backed electrical attributes visible to ZHA."""

        attr_id = self.find_attribute(attr).id
        if attr_id in self._SUPPORTED_ATTRIBUTES:
            return False
        if attr_id in self._UNSUPPORTED_ATTRIBUTES:
            return True
        return super().is_attribute_unsupported(attr)

    _CONSTANT_ATTRIBUTES = {
        **TuyaZBElectricalMeasurement._CONSTANT_ATTRIBUTES,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_current_multiplier.id: 1,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_current_divisor.id: 1000,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_power_multiplier.id: 1,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_power_divisor.id: 10,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_voltage_multiplier.id: 1,
        TuyaZBElectricalMeasurement.AttributeDefs.ac_voltage_divisor.id: 10,
    }


class O409r73pMetering(TuyaLocalCluster, TuyaZBMeteringClusterWithUnit):
    """Standard ZHA energy metering value from vendor DP20."""

    _SUPPORTED_ATTRIBUTES = _attribute_ids(
        TuyaZBMeteringClusterWithUnit.AttributeDefs,
        "current_summ_delivered",
    )
    _UNSUPPORTED_ATTRIBUTES = _attribute_ids(
        TuyaZBMeteringClusterWithUnit.AttributeDefs,
        "current_summ_received",
        "instantaneous_demand",
    )

    def is_attribute_unsupported(self, attr):
        """Expose delivered energy, and hide unsupported metering attributes."""

        attr_id = self.find_attribute(attr).id
        if attr_id in self._SUPPORTED_ATTRIBUTES:
            return False
        if attr_id in self._UNSUPPORTED_ATTRIBUTES:
            return True
        return super().is_attribute_unsupported(attr)

    _CONSTANT_ATTRIBUTES = {
        **TuyaZBMeteringClusterWithUnit._CONSTANT_ATTRIBUTES,
        TuyaZBMeteringClusterWithUnit.AttributeDefs.status.id: 0x00,
        TuyaZBMeteringClusterWithUnit.AttributeDefs.multiplier.id: 1,
        TuyaZBMeteringClusterWithUnit.AttributeDefs.divisor.id: 1000,
    }


class Countdown1Cluster(TuyaConfigNumber):
    """DP7: Relay 1 countdown in seconds."""

    dp_id = 7

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "开关1倒计时",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 43200,
        AnalogOutput.AttributeDefs.resolution.id: 1,
        AnalogOutput.AttributeDefs.engineering_units.id: 73,
    }


class Countdown2Cluster(TuyaConfigNumber):
    """DP8: Relay 2 countdown in seconds."""

    dp_id = 8

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "开关2倒计时",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 43200,
        AnalogOutput.AttributeDefs.resolution.id: 1,
        AnalogOutput.AttributeDefs.engineering_units.id: 73,
    }


class BacklightBrightnessCluster(TuyaConfigNumber):
    """DP102: Backlight brightness percentage."""

    dp_id = 102

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "Backlight brightness",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 100,
        AnalogOutput.AttributeDefs.resolution.id: 1,
        AnalogOutput.AttributeDefs.engineering_units.id: 98,
    }


class ScreenOffTimeCluster(TuyaConfigNumber):
    """DP111: Screen off delay enum: 0=never, 1=10s, 2=20s, 3=30s, 4=45s, 5=60s."""

    dp_id = 111

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "息屏时间 0=不息屏 1=10秒 2=20秒 3=30秒 4=45秒 5=60秒",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 5,
        AnalogOutput.AttributeDefs.resolution.id: 1,
    }


class PowerOnBehaviorCluster(TuyaConfigNumber):
    """DP14: Global power-on behavior enum: 0=off, 1=on, 2=memory."""

    dp_id = 14

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "上电状态设置 0=关 1=开 2=记忆",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 2,
        AnalogOutput.AttributeDefs.resolution.id: 1,
    }


class Relay1PowerOnBehaviorCluster(PowerOnBehaviorCluster):
    """DP29: Relay 1 power-on behavior enum."""

    dp_id = 29

    _CONSTANT_ATTRIBUTES = {
        **PowerOnBehaviorCluster._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "开关1上电状态 0=关 1=开 2=记忆",
    }


class Relay2PowerOnBehaviorCluster(PowerOnBehaviorCluster):
    """DP30: Relay 2 power-on behavior enum."""

    dp_id = 30

    _CONSTANT_ATTRIBUTES = {
        **PowerOnBehaviorCluster._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "开关2上电状态 0=关 1=开 2=记忆",
    }


class NightModeCluster(TuyaConfigSwitch):
    """DP13: Night mode."""

    dp_id = 13

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigSwitch._CONSTANT_ATTRIBUTES,
        BinaryOutput.AttributeDefs.description.id: "夜间模式",
    }


class RadarEnabledCluster(TuyaConfigSwitch):
    """DP16: Radar enable."""

    dp_id = 16

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigSwitch._CONSTANT_ATTRIBUTES,
        BinaryOutput.AttributeDefs.description.id: "雷达开关",
    }


class ChildLockCluster(TuyaConfigSwitch):
    """DP101: Child lock."""

    dp_id = 101

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigSwitch._CONSTANT_ATTRIBUTES,
        BinaryOutput.AttributeDefs.description.id: "Child lock",
    }


class RadarDistanceCluster(TuyaConfigNumber):
    """DP104: Radar distance enum: short, medium_short, medium, medium_long, long."""

    dp_id = 104

    _CONSTANT_ATTRIBUTES = {
        **TuyaConfigNumber._CONSTANT_ATTRIBUTES,
        AnalogOutput.AttributeDefs.description.id: "雷达距离 0=短 1=中短 2=中 3=中长 4=长",
        AnalogOutput.AttributeDefs.min_present_value.id: 0,
        AnalogOutput.AttributeDefs.max_present_value.id: 4,
        AnalogOutput.AttributeDefs.resolution.id: 1,
    }


class PowerUpTimesCluster(TuyaAttributesCluster, AnalogInput):
    """DP112: Total power-up count."""

    _CONSTANT_ATTRIBUTES = {
        AnalogInput.AttributeDefs.description.id: "上电次数",
        AnalogInput.AttributeDefs.min_present_value.id: 0,
        AnalogInput.AttributeDefs.max_present_value.id: 2100000000,
        AnalogInput.AttributeDefs.resolution.id: 1,
        AnalogInput.AttributeDefs.engineering_units.id: 95,
        AnalogInput.AttributeDefs.out_of_service.id: 0,
        AnalogInput.AttributeDefs.status_flags.id: 0,
    }


class RunTimeCluster(TuyaAttributesCluster, AnalogInput):
    """DP113: Total runtime in minutes."""

    _CONSTANT_ATTRIBUTES = {
        AnalogInput.AttributeDefs.description.id: "上电总时长",
        AnalogInput.AttributeDefs.min_present_value.id: 0,
        AnalogInput.AttributeDefs.max_present_value.id: 2100000000,
        AnalogInput.AttributeDefs.resolution.id: 1,
        AnalogInput.AttributeDefs.engineering_units.id: 72,
        AnalogInput.AttributeDefs.out_of_service.id: 0,
        AnalogInput.AttributeDefs.status_flags.id: 0,
    }


class O409r73pManufCluster(MoesSwitchManufCluster):
    """Manufacturer cluster with extra datapoint mappings for this panel."""

    attributes_to_dp_converters = {
        **getattr(MoesSwitchManufCluster, "attributes_to_dp_converters", {}),
        105: _encode_dp_string,
        106: _encode_dp_string,
    }

    dp_to_attribute = MoesSwitchManufCluster.dp_to_attribute.copy()
    for dp_id in (7, 8, 9, 13, 14, 16, 104, 107, 111, 112, 113):
        dp_to_attribute.pop(dp_id, None)

    dp_to_attribute.update(
        {
            20: DPToAttributeMapping(
                O409r73pMetering.ep_attribute,
                "current_summ_delivered",
                converter=lambda x: x,
                endpoint_id=1,
            ),
            21: DPToAttributeMapping(
                O409r73pElectricalMeasurement.ep_attribute,
                "rms_current",
                converter=lambda x: x,
                endpoint_id=1,
            ),
            22: DPToAttributeMapping(
                O409r73pElectricalMeasurement.ep_attribute,
                "active_power",
                converter=lambda x: x,
                endpoint_id=1,
            ),
            23: DPToAttributeMapping(
                O409r73pElectricalMeasurement.ep_attribute,
                "rms_voltage",
                converter=lambda x: x,
                endpoint_id=1,
            ),
            105: _name_dp_mapping("name_update_1"),
            106: _name_dp_mapping("name_update_2"),
            102: DPToAttributeMapping(
                BacklightBrightnessCluster.ep_attribute,
                "present_value",
                converter=lambda x: float(x),
                dp_converter=lambda x: int(round(x)),
                endpoint_id=8,
            ),
            101: DPToAttributeMapping(
                ChildLockCluster.ep_attribute,
                "present_value",
                converter=lambda x: bool(x),
                dp_converter=lambda x: bool(x),
                endpoint_id=12,
            ),
            29: DPToAttributeMapping(
                O409r73pRelayOnOffCluster.ep_attribute,
                "power_on_state",
                converter=_power_on_state,
                dp_converter=_power_on_state,
                endpoint_id=1,
            ),
            30: DPToAttributeMapping(
                O409r73pRelayOnOffCluster.ep_attribute,
                "power_on_state",
                converter=_power_on_state,
                dp_converter=_power_on_state,
                endpoint_id=2,
            ),
        }
    )
    data_point_handlers = MoesSwitchManufCluster.data_point_handlers.copy()
    for dp_id in (7, 8, 9, 13, 14, 16, 104, 107, 111, 112, 113):
        data_point_handlers.pop(dp_id, None)

    data_point_handlers.update(
        {
            20: "_dp_2_attr_update",
            21: "_dp_2_attr_update",
            22: "_dp_2_attr_update",
            23: "_dp_2_attr_update",
            29: "_dp_2_attr_update",
            30: "_dp_2_attr_update",
            101: "_dp_2_attr_update",
            102: "_dp_2_attr_update",
            105: "_dp_2_attr_update",
            106: "_dp_2_attr_update",
        }
    )


class O409r73p3GangManufCluster(O409r73pManufCluster):
    """3-gang manufacturer cluster with third relay DPs."""

    attributes_to_dp_converters = {
        **O409r73pManufCluster.attributes_to_dp_converters,
        107: _encode_dp_string,
    }

    dp_to_attribute = O409r73pManufCluster.dp_to_attribute.copy()
    dp_to_attribute.update(
        {
            31: DPToAttributeMapping(
                O409r73pRelayOnOffCluster.ep_attribute,
                "power_on_state",
                converter=_power_on_state,
                dp_converter=_power_on_state,
                endpoint_id=3,
            ),
            107: _name_dp_mapping("name_update_3"),
        }
    )

    data_point_handlers = O409r73pManufCluster.data_point_handlers.copy()
    data_point_handlers.update(
        {
            31: "_dp_2_attr_update",
            107: "_dp_2_attr_update",
        }
    )


class Ts0601Tze284O409r73pSwitch(TuyaSwitch):
    """Tuya TS0601 2-gang wall switch with screen and power metering.

    Device: _TZE284_o409r73p
    Features:
    - 2 relay outputs (Endpoint 1 & 2)
    - Power metering via AnalogInput (Endpoint 6-13)
    - Display name sync
    - Backlight, child lock, power-on state, and metering
    """

    quirk_id = (TUYA_PLUG_ONOFF,)

    signature = {
        MODELS_INFO: [
            ("_TZE284_o409r73p", "TS0601"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,        # 0x0000
                    Groups.cluster_id,        # 0x0004
                    Scenes.cluster_id,        # 0x0005
                    OnOff.cluster_id,        # 0x0006
                    0xEF00,                  # Tuya
                ],
                OUTPUT_CLUSTERS: [
                    Time.cluster_id,         # 0x000A
                    Ota.cluster_id,           # 0x0019
                ],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    OnOff.cluster_id,         # 0x0006
                ],
                OUTPUT_CLUSTERS: [],
            },
            6: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],    # AnalogInput - power data
                OUTPUT_CLUSTERS: [],
            },
            7: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            8: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            9: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            10: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            11: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            12: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            13: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [0x000D],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    O409r73pManufCluster,
                    O409r73pRelayOnOffCluster,
                    O409r73pElectricalMeasurement,
                    O409r73pMetering,
                ],
                OUTPUT_CLUSTERS: [
                    Time.cluster_id,
                    Ota.cluster_id,
                ],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                INPUT_CLUSTERS: [O409r73pRelayOnOffCluster],
                OUTPUT_CLUSTERS: [],
            },
            8: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [BacklightBrightnessCluster],
                OUTPUT_CLUSTERS: [],
            },
            12: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [ChildLockCluster],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }


class Ts0601Tze28C1000000O409r73pSwitch(Ts0601Tze284O409r73pSwitch):
    """Same o409r73p panel with the newer TZE28C1000000 fingerprint."""

    signature = {
        MODELS_INFO: [
            ("_TZE28C1000000_o409r73p", "TS0601"),
        ],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    0xE000,
                    0xEB00,
                    0xED00,
                    0xEF00,
                ],
                OUTPUT_CLUSTERS: [
                    Time.cluster_id,
                    Ota.cluster_id,
                ],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }


class Ts0601Tze284Oy1nuaa5Switch(Ts0601Tze284O409r73pSwitch):
    """ZMZ609 3-gang panel with screen, radar controls and power metering."""

    signature = {
        MODELS_INFO: [
            ("_TZE284_oy1nuaa5", "TS0601"),
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
                    0xEF00,
                ],
                OUTPUT_CLUSTERS: [
                    Time.cluster_id,
                    Ota.cluster_id,
                ],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    O409r73p3GangManufCluster,
                    O409r73pRelayOnOffCluster,
                    O409r73pElectricalMeasurement,
                    O409r73pMetering,
                ],
                OUTPUT_CLUSTERS: [
                    Time.cluster_id,
                    Ota.cluster_id,
                ],
            },
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                INPUT_CLUSTERS: [O409r73pRelayOnOffCluster],
                OUTPUT_CLUSTERS: [],
            },
            3: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                INPUT_CLUSTERS: [O409r73pRelayOnOffCluster],
                OUTPUT_CLUSTERS: [],
            },
            8: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [BacklightBrightnessCluster],
                OUTPUT_CLUSTERS: [],
            },
            12: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.COMBINED_INTERFACE,
                INPUT_CLUSTERS: [ChildLockCluster],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }
