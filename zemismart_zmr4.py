"""ZHA quirk for the Zemismart ZMR4 four-button Zigbee remote.

Supported fingerprint:
* TS0044 / _TZ3000_xwuveizv

Each of the four endpoints emits ``short_press``, ``double_press`` and
``long_press`` events.  Only endpoint 1 exposes the shared battery value; the
physical remote reports one battery, not four independent batteries.
"""

from __future__ import annotations

from typing import Final

import zigpy.types as t
from zha.application import EntityPlatform, EntityType
from zigpy.profiles import zha
from zigpy.zcl import ClusterType, foundation
from zigpy.zcl.clusters.general import Basic, Ota, PowerConfiguration, Time

from zhaquirks.builder import QuirkBuilder
from zhaquirks.const import (
    BUTTON_1,
    BUTTON_2,
    BUTTON_3,
    BUTTON_4,
    COMMAND,
    DOUBLE_PRESS,
    ENDPOINT_ID,
    LONG_PRESS,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.tuya import (
    TuyaNoBindPowerConfigurationCluster,
    TuyaSmartRemoteOnOffCluster,
)


class ZMR4Action(t.enum8):
    """Last physical action reported by one ZMR4 button."""

    single_press = 0x00
    double_press = 0x01
    long_press = 0x02


class ZMR4OnOffCluster(TuyaSmartRemoteOnOffCluster):
    """Tuya action cluster with a local attribute for a visible HA sensor."""

    class AttributeDefs(TuyaSmartRemoteOnOffCluster.AttributeDefs):
        """Standard Tuya attributes plus the locally maintained action."""

        last_action: Final = foundation.ZCLAttributeDef(
            id=0xF000,
            type=ZMR4Action,
            access="r",
        )

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: list,
        *,
        dst_addressing=None,
    ) -> None:
        """Keep the standard ZHA event and mirror it into ``last_action``."""

        duplicate = hdr.tsn == self.last_tsn
        super().handle_cluster_request(
            hdr,
            args,
            dst_addressing=dst_addressing,
        )

        if (
            duplicate
            or hdr.command_id != self.ServerCommandDefs.press_type.id
            or not args
        ):
            return

        try:
            action = ZMR4Action(int(args[0]))
        except (TypeError, ValueError):
            return

        self._update_attribute(self.AttributeDefs.last_action.id, action)

    async def simulate_press(self, press_type: int) -> None:
        """Emit one local ZHA action without sending a command to the remote."""

        try:
            action = ZMR4Action(press_type)
        except (TypeError, ValueError):
            return

        event = self.press_type.get(int(action))
        if event is None:
            return

        self._update_attribute(self.AttributeDefs.last_action.id, action)
        self.listener_event(ZHA_SEND_EVENT, event, [])


ZMR4_TRIGGERS = {
    (SHORT_PRESS, BUTTON_1): {ENDPOINT_ID: 1, COMMAND: SHORT_PRESS},
    (DOUBLE_PRESS, BUTTON_1): {ENDPOINT_ID: 1, COMMAND: DOUBLE_PRESS},
    (LONG_PRESS, BUTTON_1): {ENDPOINT_ID: 1, COMMAND: LONG_PRESS},
    (SHORT_PRESS, BUTTON_2): {ENDPOINT_ID: 2, COMMAND: SHORT_PRESS},
    (DOUBLE_PRESS, BUTTON_2): {ENDPOINT_ID: 2, COMMAND: DOUBLE_PRESS},
    (LONG_PRESS, BUTTON_2): {ENDPOINT_ID: 2, COMMAND: LONG_PRESS},
    (SHORT_PRESS, BUTTON_3): {ENDPOINT_ID: 3, COMMAND: SHORT_PRESS},
    (DOUBLE_PRESS, BUTTON_3): {ENDPOINT_ID: 3, COMMAND: DOUBLE_PRESS},
    (LONG_PRESS, BUTTON_3): {ENDPOINT_ID: 3, COMMAND: LONG_PRESS},
    (SHORT_PRESS, BUTTON_4): {ENDPOINT_ID: 4, COMMAND: SHORT_PRESS},
    (DOUBLE_PRESS, BUTTON_4): {ENDPOINT_ID: 4, COMMAND: DOUBLE_PRESS},
    (LONG_PRESS, BUTTON_4): {ENDPOINT_ID: 4, COMMAND: LONG_PRESS},
}

ZMR4_SIMULATED_ACTIONS = (
    (ZMR4Action.single_press, "single_press", "single press"),
    (ZMR4Action.double_press, "double_press", "double press"),
    (ZMR4Action.long_press, "long_press", "long press"),
)


zmr4 = QuirkBuilder("_TZ3000_xwuveizv", "TS0044")

for endpoint_id in range(1, 5):
    zmr4.replaces_endpoint(
        endpoint_id=endpoint_id,
        profile_id=zha.PROFILE_ID,
        device_type=zha.DeviceType.REMOTE_CONTROL,
    )
    zmr4.adds(ZMR4OnOffCluster, endpoint_id=endpoint_id)
    zmr4.enum(
        attribute_name=ZMR4OnOffCluster.AttributeDefs.last_action.name,
        enum_class=ZMR4Action,
        cluster_id=ZMR4OnOffCluster.cluster_id,
        endpoint_id=endpoint_id,
        entity_platform=EntityPlatform.SENSOR,
        entity_type=EntityType.STANDARD,
        unique_id_suffix=f"button_{endpoint_id}_action",
        translation_key="button_action",
        fallback_name=f"Button {endpoint_id} action",
    )
    for action, action_suffix, action_name in ZMR4_SIMULATED_ACTIONS:
        zmr4.command_button(
            command_name="simulate_press",
            command_args=(int(action),),
            cluster_id=ZMR4OnOffCluster.cluster_id,
            endpoint_id=endpoint_id,
            entity_type=EntityType.STANDARD,
            unique_id_suffix=f"button_{endpoint_id}_{action_suffix}",
            translation_key=f"button_{endpoint_id}_{action_suffix}",
            fallback_name=f"Button {endpoint_id} {action_name}",
        )

for endpoint_id in range(2, 5):
    zmr4.removes(PowerConfiguration.cluster_id, endpoint_id=endpoint_id)

zmr4.adds(Basic, endpoint_id=1)
zmr4.adds(TuyaNoBindPowerConfigurationCluster, endpoint_id=1)
zmr4.adds(Time, cluster_type=ClusterType.Client, endpoint_id=1)
zmr4.adds(Ota, cluster_type=ClusterType.Client, endpoint_id=1)

(
    zmr4.friendly_name(manufacturer="Zemismart", model="ZMR4")
    .device_automation_triggers(ZMR4_TRIGGERS)
    .skip_configuration()
    .add_to_registry()
)
