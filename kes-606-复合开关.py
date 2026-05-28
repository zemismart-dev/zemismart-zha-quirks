"""Zemismart KES 606 composite scene switches for ZHA.

This standalone quirk is intentionally separate from older KES 606 files.
Place it in /config/zha_quirks/ and restart Home Assistant.

Supported fingerprints:
* TS0726 / _TZ3000_ovbvmhiq: 1 gang
* TS0726 / _TZ3000_icoxotza: 2 gang
* TS0726 / _TZ3000_cziew6eu: 3 gang
* TS0726 / _TZ3000_hurauima: 4 gang
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import zigpy.types as t
from zigpy.quirks import CustomCluster
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
from zigpy.quirks.v2.homeassistant import EntityType
from zigpy.typing import UNDEFINED, UndefinedType
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import BaseAttributeDefs, ZCLAttributeDef

from zhaquirks.const import (
    BUTTON_1,
    BUTTON_2,
    BUTTON_3,
    BUTTON_4,
    CLUSTER_ID,
    COMMAND,
    COMMAND_ID,
    ENDPOINT_ID,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.tuya import BaseEnchantedDevice


TUYA_PRIVATE_CLUSTER_ID = 0xE001


class KES606SwitchMode(t.enum8):
    """Per-gang Tuya work mode."""

    switch = 0x00
    scene = 0x01


class KES606PowerOnBehavior(t.enum8):
    """Relay state after power is restored."""

    off = 0x00
    on = 0x01
    previous = 0x02


def _attribute_id(
    attribute: str | int | foundation.ZCLAttributeDef,
    attribute_defs: type[BaseAttributeDefs],
) -> int | None:
    """Return an attribute id from current and older zigpy key shapes."""

    if isinstance(attribute, str):
        definition = getattr(attribute_defs, attribute, None)
        return None if definition is None else definition.id

    if isinstance(attribute, int):
        return int(attribute)

    return getattr(attribute, "id", None)


def _attribute_value(value: Any) -> Any:
    """Unwrap zigpy typed values when write_attributes receives a record value."""

    return getattr(value, "value", value)


class KES606PrivateCluster(CustomCluster):
    """Tuya private cluster 0xE001 used by TS0726 scene switches."""

    name = "KES 606 private"
    cluster_id = TUYA_PRIVATE_CLUSTER_ID
    ep_attribute = "kes_606_private"

    class AttributeDefs(BaseAttributeDefs):
        """Tuya private attributes used by this family."""

        power_on_behavior: Final = ZCLAttributeDef(
            id=0xD010,
            type=KES606PowerOnBehavior,
            access="rw",
        )
        switch_mode: Final = ZCLAttributeDef(
            id=0xD020,
            type=KES606SwitchMode,
            access="rw",
        )
        switch_type: Final = ZCLAttributeDef(
            id=0xD030,
            type=t.enum8,
            access="rw",
        )

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs: Any,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Write attributes and update cache for immediate scene-mode guarding."""

        result = await super().write_attributes(
            attributes,
            manufacturer=manufacturer,
            **kwargs,
        )

        for attribute, value in attributes.items():
            attrid = _attribute_id(attribute, self.AttributeDefs)
            if attrid is not None:
                self._update_attribute(attrid, _attribute_value(value))

        return result


class KES606Device(BaseEnchantedDevice, CustomDeviceV2):
    """TS0726 devices need Tuya attribute reads before normal operation."""

    tuya_spell_read_attributes = True
    tuya_spell_data_query = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Run the Tuya spell after HA recreates an already-paired device."""

        super().__init__(*args, **kwargs)
        try:
            self.create_task(
                self._run_startup_tuya_spell(),
                name=f"kes606-startup-tuya-spell-{self.ieee}",
            )
        except RuntimeError:
            self.debug("Could not schedule KES606 startup Tuya spell")

    async def _run_startup_tuya_spell(self) -> None:
        """Read Tuya magic attributes on startup, not only during reconfigure."""

        for attempt in range(1, 4):
            await asyncio.sleep(attempt * 2)
            try:
                self.debug(
                    "Executing KES606 startup Tuya spell attempt %s for %s",
                    attempt,
                    self.ieee,
                )
                await self.spell_attribute_reads()
                self.debug("Executed KES606 startup Tuya spell for %s", self.ieee)
                return
            except Exception as exc:  # noqa: BLE001 - startup recovery must be best effort
                self.debug(
                    "KES606 startup Tuya spell attempt %s failed for %s: %r",
                    attempt,
                    self.ieee,
                    exc,
                )


class KES606OnOffCluster(CustomCluster, OnOff):
    """OnOff cluster with scene-mode relay protection and scene events."""

    name = "KES 606 scene guarded on/off"
    ep_attribute = "on_off"

    class AttributeDefs(OnOff.AttributeDefs):
        """Standard OnOff attributes plus Tuya TS0726 private attributes."""

        moes_start_up_on_off: Final = ZCLAttributeDef(
            id=0x8002,
            type=KES606PowerOnBehavior,
            access="rw",
        )
        tuya_operation_mode: Final = ZCLAttributeDef(
            id=0x8004,
            type=KES606SwitchMode,
            access="rw",
        )

    class ServerCommandDefs(OnOff.ServerCommandDefs):
        """Standard OnOff commands plus Tuya action commands."""

        tuya_action_2: Final = foundation.ZCLCommandDef(
            id=0xFC,
            schema={"value": t.uint8_t},
            is_manufacturer_specific=True,
        )
        tuya_action: Final = foundation.ZCLCommandDef(
            id=0xFD,
            schema={"value": t.uint8_t, "data": t.LVBytes},
            is_manufacturer_specific=True,
        )

    RELAY_COMMANDS = {
        OnOff.ServerCommandDefs.off.id,
        OnOff.ServerCommandDefs.on.id,
        OnOff.ServerCommandDefs.toggle.id,
        OnOff.ServerCommandDefs.off_with_effect.id,
        OnOff.ServerCommandDefs.on_with_recall_global_scene.id,
        OnOff.ServerCommandDefs.on_with_timed_off.id,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize duplicate-action tracking."""

        super().__init__(*args, **kwargs)
        self._last_action_tsn: int | None = None

    def _is_scene_mode(self) -> bool:
        """Return True when this endpoint is set to scene mode."""

        private_cluster = self.endpoint.in_clusters.get(TUYA_PRIVATE_CLUSTER_ID)
        if private_cluster is not None:
            value = private_cluster.get(KES606PrivateCluster.AttributeDefs.switch_mode.id)
            if value is not None:
                return int(value) == int(KES606SwitchMode.scene)

        value = self.get(self.AttributeDefs.tuya_operation_mode.id)
        return value is not None and int(value) == int(KES606SwitchMode.scene)

    @staticmethod
    def _default_response(command_id: int, status: foundation.Status):
        """Build a Zigbee default response payload."""

        return foundation.GENERAL_COMMANDS[
            foundation.GeneralCommand.Default_Response
        ].schema(command_id=command_id, status=status)

    def _restore_on_off_state(self, previous_state: Any) -> None:
        """Restore HA's optimistic switch cache after a scene-mode no-op."""

        if previous_state is not None:
            self.update_attribute(OnOff.AttributeDefs.on_off.id, previous_state)

    async def command(
        self,
        command_id: foundation.GeneralCommand | int | t.uint8_t,
        *args: Any,
        manufacturer: int | t.uint16_t | None = None,
        expect_reply: bool = True,
        tsn: int | t.uint8_t | None = None,
        **kwargs: Any,
    ):
        """Suppress app relay control while a gang is in scene mode."""

        command_id_int = int(command_id)
        if command_id_int in self.RELAY_COMMANDS and self._is_scene_mode():
            previous_state = self.get(OnOff.AttributeDefs.on_off.id)
            self.debug(
                "Blocked relay command 0x%02x on endpoint %s because switch_mode=scene",
                command_id_int,
                self.endpoint.endpoint_id,
            )
            loop = asyncio.get_running_loop()
            loop.call_soon(self._restore_on_off_state, previous_state)
            loop.call_later(0.2, self._restore_on_off_state, previous_state)
            return self._default_response(command_id_int, foundation.Status.SUCCESS)

        if command_id_int in (
            OnOff.ServerCommandDefs.off.id,
            OnOff.ServerCommandDefs.on.id,
            OnOff.ServerCommandDefs.toggle.id,
        ):
            manufacturer = None if manufacturer is UNDEFINED else manufacturer
            command = self.server_commands[command_id_int]
            header, request = self._create_request(
                general=False,
                command_id=command_id_int,
                schema=command.schema,
                *args,
                manufacturer=manufacturer,
                tsn=tsn,
                disable_default_response=False,
                direction=(
                    foundation.Direction.Server_to_Client
                    if self.is_client
                    else foundation.Direction.Client_to_Server
                ),
                args=args,
                kwargs=kwargs,
            )

            self.debug(
                "Sending KES606 OnOff command 0x%02x with src_ep=1 dst_ep=%s",
                command_id_int,
                self.endpoint.endpoint_id,
            )
            return await self.endpoint.device.request(
                profile=self.endpoint.profile_id,
                cluster=self.cluster_id,
                src_ep=1,
                dst_ep=self.endpoint.endpoint_id,
                sequence=header.tsn,
                data=header.serialize() + request.serialize(),
                expect_reply=expect_reply,
            )

        return await super().command(
            command_id,
            *args,
            manufacturer=manufacturer,
            expect_reply=expect_reply,
            tsn=tsn,
            **kwargs,
        )

    def handle_cluster_request(
        self,
        hdr: foundation.ZCLHeader,
        args: list[Any],
        **kwargs: Any,
    ) -> None:
        """Convert Tuya scene commands into ZHA device automation events."""

        if hdr.command_id in (0xFC, 0xFD):
            if hdr.tsn == self._last_action_tsn:
                return
            self._last_action_tsn = hdr.tsn

            if not hdr.frame_control.disable_default_response:
                self.send_default_rsp(hdr, status=foundation.Status.SUCCESS)

            action = f"scene_{self.endpoint.endpoint_id}"
            self.listener_event(
                ZHA_SEND_EVENT,
                action,
                {
                    COMMAND: action,
                    ENDPOINT_ID: self.endpoint.endpoint_id,
                    CLUSTER_ID: self.cluster_id,
                    COMMAND_ID: hdr.command_id,
                },
            )
            return

        return super().handle_cluster_request(hdr, args, **kwargs)


BUTTONS_BY_ENDPOINT = {
    1: BUTTON_1,
    2: BUTTON_2,
    3: BUTTON_3,
    4: BUTTON_4,
}

KES606_VARIANTS: tuple[tuple[str, int, str], ...] = (
    ("_TZ3000_ovbvmhiq", 1, "KES 606 composite scene switch 1 gang"),
    ("_TZ3000_icoxotza", 2, "KES 606 composite scene switch 2 gang"),
    ("_TZ3000_cziew6eu", 3, "KES 606 composite scene switch 3 gang"),
    ("_TZ3000_hurauima", 4, "KES 606 composite scene switch 4 gang"),
)


def _scene_triggers(gang_count: int) -> dict[tuple[str, str], dict[str, int | str]]:
    """Build ZHA device automation triggers for each scene endpoint."""

    return {
        (SHORT_PRESS, BUTTONS_BY_ENDPOINT[endpoint_id]): {
            COMMAND: f"scene_{endpoint_id}",
            ENDPOINT_ID: endpoint_id,
            CLUSTER_ID: KES606OnOffCluster.cluster_id,
        }
        for endpoint_id in range(1, gang_count + 1)
    }


def _register_kes606_variant(
    manufacturer_name: str,
    gang_count: int,
    model_name: str,
) -> None:
    """Register one TS0726 KES 606 variant."""

    builder = (
        QuirkBuilder(manufacturer_name, "TS0726")
        .device_class(KES606Device)
        .friendly_name(manufacturer="Zemismart", model=model_name)
        .device_automation_triggers(_scene_triggers(gang_count))
    )

    for endpoint_id in range(1, gang_count + 1):
        builder = (
            builder.replaces(KES606OnOffCluster, endpoint_id=endpoint_id)
            .replaces(KES606PrivateCluster, endpoint_id=endpoint_id)
            .enum(
                "switch_mode",
                KES606SwitchMode,
                cluster_id=KES606PrivateCluster.cluster_id,
                endpoint_id=endpoint_id,
                entity_type=EntityType.CONFIG,
                unique_id_suffix=f"switch_mode_{endpoint_id}",
                translation_key="switch_mode",
                fallback_name=f"L{endpoint_id} switch mode",
            )
            .enum(
                "power_on_behavior",
                KES606PowerOnBehavior,
                cluster_id=KES606PrivateCluster.cluster_id,
                endpoint_id=endpoint_id,
                entity_type=EntityType.CONFIG,
                unique_id_suffix=f"power_on_behavior_{endpoint_id}",
                translation_key="power_on_behavior",
                fallback_name=f"L{endpoint_id} power on behavior",
            )
        )

    builder.add_to_registry()


for _manufacturer_name, _gang_count, _model_name in KES606_VARIANTS:
    _register_kes606_variant(_manufacturer_name, _gang_count, _model_name)
