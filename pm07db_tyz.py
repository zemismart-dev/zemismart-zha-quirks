"""ZHA quirk for the Zemismart PF-PM07D battery water valve.

Supported fingerprint:
* TS0601 / _TZE2841000000_zm8zpwas

Confirmed Tuya datapoints:
* DP 1: valve control (off / on)
* DP 7: work state (opening / closing / idle; parsed internally)
* DP 8: valve state (unknown / open / closed; parsed internally)
* DP 10: raw fault bitmap
* DP 101: battery percentage
"""

from __future__ import annotations

import asyncio

import zigpy.types as t
from zha.application import EntityType
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import PowerConfiguration

from zhaquirks import CustomCluster
from zhaquirks.device import CustomZigpyDevice
from zhaquirks.tuya import BaseEnchantedDevice
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import TuyaMCUCluster


class ValveWorkState(t.enum8):
    """DP 7 motor work state reported by the valve."""

    opening = 0x00
    closing = 0x01
    idle = 0x02


class ValveState(t.enum8):
    """DP 8 end-state reported by the valve."""

    unknown = 0x00
    open = 0x01
    closed = 0x02


READ_REPORT_ACCESS = (
    foundation.ZCLAttributeAccess.Read | foundation.ZCLAttributeAccess.Report
)


class PFPM07DPowerConfigurationCluster(CustomCluster, PowerConfiguration):
    """Real Power Configuration cluster with DP 101 as a second input path."""


class PFPM07DDevice(CustomZigpyDevice, BaseEnchantedDevice):
    """Query the sleepy valve whenever it announces after waking."""

    tuya_spell_read_attributes = True
    tuya_spell_data_query = True

    def __init__(self, *args, **kwargs):
        """Listen for this device's ZDO announce events."""

        super().__init__(*args, **kwargs)
        self.zdo.add_listener(self)
        self._battery_configuration_lock = asyncio.Lock()
        self._battery_reporting_configured = False

    async def apply_custom_configuration(self, *args, **kwargs):
        """Apply the Tuya unlock sequence and configure standard battery reports."""

        await super().apply_custom_configuration(*args, **kwargs)
        await self._configure_battery_reporting()

    def device_announce(self, device):
        """Refresh all Tuya DPs inside the device's short wake window."""

        if device is self:
            self.create_task(
                self._refresh_data_after_announce(),
                name=f"PF-PM07D Tuya refresh {self.ieee}",
            )

    async def _refresh_data_after_announce(self):
        """Unlock Tuya reporting and query DPs after a button wake-up."""

        try:
            await self.spell_attribute_reads()
            await self.spell_data_query()
            await self._configure_battery_reporting()
        except Exception as error:  # noqa: BLE001 - log protocol failures
            self.warning("PF-PM07D Tuya refresh after announce failed: %s", error)

    async def _configure_battery_reporting(self):
        """Match the standard battery setup confirmed with Zigbee2MQTT."""

        if self._battery_reporting_configured:
            return

        async with self._battery_configuration_lock:
            if self._battery_reporting_configured:
                return

            power_cluster = self.endpoints[1].in_clusters[
                PowerConfiguration.cluster_id
            ]
            battery_attribute = (
                PowerConfiguration.AttributeDefs.battery_percentage_remaining
            )

            bind_result = await power_cluster.bind()
            if not bind_result or bind_result[0] != foundation.Status.SUCCESS:
                raise RuntimeError(f"battery cluster bind failed: {bind_result!r}")

            reporting_result = await power_cluster.configure_reporting(
                battery_attribute,
                min_interval=3600,
                max_interval=65000,
                reportable_change=10,
            )
            if reporting_result.get(battery_attribute) != foundation.Status.SUCCESS:
                raise RuntimeError(
                    f"battery reporting configuration failed: {reporting_result!r}"
                )

            read_success, read_failure = await power_cluster.read_attributes(
                [battery_attribute.name]
            )
            if battery_attribute.name not in read_success:
                raise RuntimeError(
                    "battery percentage read failed: "
                    f"success={read_success!r}, failure={read_failure!r}"
                )

            self._battery_reporting_configured = True
            self.debug(
                "PF-PM07D battery reporting configured; raw percentage=%s",
                read_success[battery_attribute.name],
            )


class PFPM07DTuyaMCUCluster(TuyaMCUCluster):
    """Send DP writes in the frame form accepted by this valve firmware."""

    def from_cluster_data(self, cluster_data):
        """Use the fixed Tuya transaction sequence used by this firmware."""

        commands = super().from_cluster_data(cluster_data)
        for command in commands:
            command.tsn = 1
        return commands

    async def command(self, command_id, *args, **kwargs):
        """Disable the default ZCL response for Tuya set-data commands.

        Match the confirmed Zigbee2MQTT write: disable the default ZCL response,
        use a fixed Tuya sequence of 1, and do not request an APS ACK.
        """

        if int(command_id) != int(self.mcu_write_command):
            return await super().command(command_id, *args, **kwargs)

        kwargs.setdefault("disable_default_response", True)
        kwargs.setdefault("ask_for_ack", False)
        return await super().command(command_id, *args, **kwargs)


(
    TuyaQuirkBuilder("_TZE2841000000_zm8zpwas", "TS0601")
    .friendly_name(manufacturer="Zemismart", model="PF-PM07D")
    .device_class(PFPM07DDevice)
    .tuya_switch(
        dp_id=1,
        attribute_name="valve",
        entity_type=EntityType.STANDARD,
        translation_key="valve",
        fallback_name="Valve",
    )
    # Keep DP7/DP8 available to the cluster cache for diagnostics, but do not
    # publish HA entities because reports were not observed on the current ZHA path.
    .tuya_dp_attribute(
        dp_id=7,
        attribute_name="work_state",
        type=ValveWorkState,
        access=READ_REPORT_ACCESS,
    )
    .tuya_dp_attribute(
        dp_id=8,
        attribute_name="valve_state",
        type=ValveState,
        access=READ_REPORT_ACCESS,
    )
    .tuya_sensor(
        dp_id=10,
        attribute_name="fault_code",
        type=t.uint32_t,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key="fault_code",
        fallback_name="Fault code",
    )
    # The device also reports the standard battery percentage attribute. Mapping
    # DP101 to the same cluster keeps either reporting path authoritative.
    .tuya_battery(
        dp_id=101,
        power_cfg=PFPM07DPowerConfigurationCluster,
    )
    .skip_configuration()
    .add_to_registry(replacement_cluster=PFPM07DTuyaMCUCluster)
)
