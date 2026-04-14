import logging

from zigpy.profiles import zha, zgp
from zigpy.zcl.clusters.general import Basic, GreenPowerProxy, Groups, Identify, Ota, Scenes, Time
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya import TuyaData, TuyaSwitch
from zhaquirks.tuya.mcu import DPToAttributeMapping, MoesSwitchManufCluster, TuyaOnOffNM


_LOGGER = logging.getLogger(__name__)


class RawBytes(TuyaData):
    def __init__(self, value: bytes):
        self.raw = value

    def serialize(self) -> bytes:
        length = len(self.raw)
        return b"\x00" + length.to_bytes(2, "big") + self.raw

    def __repr__(self):
        return f"<RawBytes {self.raw!r}>"


def _name_dp_mapping(dp_id: int, attribute_name: str) -> DPToAttributeMapping:
    return DPToAttributeMapping(
        ep_attribute="tuya_mcu",
        attribute_name=attribute_name,
        converter=lambda x: x.decode("utf-8"),
        dp_converter=lambda x: RawBytes(x.encode("utf-8")),
        endpoint_id=1,
    )


class CustomMoesSwitchManufCluster_1G(MoesSwitchManufCluster):
    """Custom Moes cluster with 1 gang screen name support."""

    dp_to_attribute = MoesSwitchManufCluster.dp_to_attribute.copy()
    dp_to_attribute.update({
        105: _name_dp_mapping(105, "name_update_1"),
    })
    data_point_handlers = MoesSwitchManufCluster.data_point_handlers.copy()


class CustomMoesSwitchManufCluster_2G(MoesSwitchManufCluster):
    """Custom Moes cluster with 2 gang screen name support."""

    dp_to_attribute = MoesSwitchManufCluster.dp_to_attribute.copy()
    dp_to_attribute.update({
        105: _name_dp_mapping(105, "name_update_1"),
        106: _name_dp_mapping(106, "name_update_2"),
    })
    data_point_handlers = MoesSwitchManufCluster.data_point_handlers.copy()


class CustomMoesSwitchManufCluster_3G(MoesSwitchManufCluster):
    """Custom Moes cluster with 3 gang screen name support."""

    dp_to_attribute = MoesSwitchManufCluster.dp_to_attribute.copy()
    dp_to_attribute.update({
        105: _name_dp_mapping(105, "name_update_1"),
        106: _name_dp_mapping(106, "name_update_2"),
        107: _name_dp_mapping(107, "name_update_3"),
    })
    data_point_handlers = MoesSwitchManufCluster.data_point_handlers.copy()


class CustomMoesSwitchManufCluster_4G(MoesSwitchManufCluster):
    """Custom Moes cluster with 4 gang screen name support."""

    dp_to_attribute = MoesSwitchManufCluster.dp_to_attribute.copy()
    dp_to_attribute.update({
        105: _name_dp_mapping(105, "name_update_1"),
        106: _name_dp_mapping(106, "name_update_2"),
        107: _name_dp_mapping(107, "name_update_3"),
        108: _name_dp_mapping(108, "name_update_4"),
    })
    data_point_handlers = MoesSwitchManufCluster.data_point_handlers.copy()


def _signature(models_info, input_clusters=None):
    if input_clusters is None:
        input_clusters = [
            Basic.cluster_id,
            Groups.cluster_id,
            Scenes.cluster_id,
            MoesSwitchManufCluster.cluster_id,
            0xED00,
        ]

    return {
        MODELS_INFO: models_info,
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.SMART_PLUG,
                INPUT_CLUSTERS: input_clusters,
                OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }


def _replacement(manufacturer_cluster, channels: int):
    endpoints = {
        1: {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
            INPUT_CLUSTERS: [
                Basic.cluster_id,
                Groups.cluster_id,
                Scenes.cluster_id,
                manufacturer_cluster,
                TuyaOnOffNM,
            ],
            OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
        },
        242: {
            PROFILE_ID: zgp.PROFILE_ID,
            DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
            INPUT_CLUSTERS: [],
            OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
        },
    }

    for endpoint_id in range(2, channels + 1):
        endpoints[endpoint_id] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
            INPUT_CLUSTERS: [TuyaOnOffNM],
            OUTPUT_CLUSTERS: [],
        }

    return {ENDPOINTS: endpoints}


def _tze28c1000000_signature(models_info):
    return _signature(
        models_info,
        [
            Basic.cluster_id,
            0xE000,
            0xEB00,
            0xED00,
            Groups.cluster_id,
            Scenes.cluster_id,
            Identify.cluster_id,
            0xEF00,
        ],
    )


def _tze204_ef00_signature(models_info):
    return _signature(
        models_info,
        [
            Groups.cluster_id,
            Scenes.cluster_id,
            0xEF00,
            Basic.cluster_id,
        ],
    )


class TuyaSingleSwitch_GP(TuyaSwitch):
    """Tuya single channel screen switch."""

    signature = _signature([
        ("_TZE284_lnyz4a6v", "TS0601"),
        ("_TZE284_1tnysxwl", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_1G, 1)


class TuyaDualSwitch_GP(TuyaSwitch):
    """Tuya dual channel screen switch."""

    signature = _signature([
        ("_TZE284_dmckrsxg", "TS0601"),
        ("_TZE284_a2teqi5u", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_2G, 2)


class TuyaDualSwitch_GP_TZE28C1000000(TuyaSwitch):
    """Tuya dual channel screen switch with TZE28C1000000 signature."""

    signature = _tze28c1000000_signature([
        ("_TZE28C1000000_a2teqi5u", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_2G, 2)


class TuyaDualSwitch_GP_TZE204_EF00(TuyaSwitch):
    """Tuya dual channel screen switch with EF00-only TZE204 signature."""

    signature = _tze204_ef00_signature([
        ("_TZE204_3ctwoaip", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_2G, 2)


class TuyaTripleSwitch_GP(TuyaSwitch):
    """Tuya triple channel screen switch."""

    signature = _signature([
        ("_TZE284_e4pf6l87", "TS0601"),
        ("_TZE284_xvywzhmi", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_3G, 3)


class TuyaQuadrupleSwitch_GP(TuyaSwitch):
    """Tuya quadruple channel screen switch."""

    signature = _signature([
        ("_TZE284_y4jqpry8", "TS0601"),
        ("_TZE284_xibaabmu", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_4G, 4)


class TuyaQuadrupleSwitch_GP_TZE28C1000000(TuyaSwitch):
    """Tuya quadruple channel screen switch with TZE28C1000000 signature."""

    signature = _tze28c1000000_signature([
        ("_TZE28C1000000_xibaabmu", "TS0601"),
    ])
    replacement = _replacement(CustomMoesSwitchManufCluster_4G, 4)
