"""Zemismart ZN2S-L01E-SMB TS0601 switch/scene mode quirks."""

from __future__ import annotations

from typing import Any

import zigpy.types as t
from zigpy.quirks.v2.homeassistant import EntityType
from zigpy.typing import UNDEFINED, UndefinedType
from zigpy.zcl import foundation

from zhaquirks.const import (
    BUTTON_1,
    BUTTON_2,
    BUTTON_3,
    BUTTON_4,
    CLUSTER_ID,
    COMMAND,
    SHORT_PRESS,
    ZHA_SEND_EVENT,
)
from zhaquirks.tuya import TUYA_CLUSTER_ID
from zhaquirks.tuya.builder import TuyaQuirkBuilder
from zhaquirks.tuya.mcu import DPToAttributeMapping, TuyaMCUCluster


SCENE_SWITCH_SIGNATURES: tuple[tuple[str, int], ...] = (
    ("_TZE200_ephrk8to", 1),
    ("_TZE200_ahyyfhqk", 2),
    ("_TZE200_zuphzsmo", 3),
    ("_TZE200_6si1pnia", 4),
)

BUTTONS = {
    1: BUTTON_1,
    2: BUTTON_2,
    3: BUTTON_3,
    4: BUTTON_4,
}

SCENE_DP_TO_COMMAND = {
    1: "scene_1",
    2: "scene_2",
    3: "scene_3",
    4: "scene_4",
}

RELAY_ATTR_TO_MODE_ATTR = {
    f"state_l{gang}": f"switch_mode_l{gang}" for gang in range(1, 5)
}


class SceneSwitchMode(t.enum8):
    """Per-gang switch mode."""

    switch = 0x00
    scene = 0x01


def _as_switch_mode(value: Any) -> SceneSwitchMode:
    """Convert Tuya mode values to the ZHA select enum."""
    return SceneSwitchMode(value)


def _is_scene_mode(value: Any) -> bool:
    """Return True when a gang is configured as a scene button."""
    try:
        return int(value) == int(SceneSwitchMode.scene)
    except (TypeError, ValueError):
        return value == SceneSwitchMode.scene or value == "scene"


class SceneSwitchTuyaCluster(TuyaMCUCluster):
    """Tuya MCU cluster with scene events and mode-aware relay writes."""

    @staticmethod
    def _attribute_name(
        attr: str | int | foundation.ZCLAttributeDef,
        attributes: dict[int, foundation.ZCLAttributeDef],
    ) -> str:
        """Resolve an attribute key into its ZCL attribute name."""
        if isinstance(attr, str):
            return attr
        if isinstance(attr, foundation.ZCLAttributeDef):
            return attr.name
        return attributes[int(attr)].name

    def _handle_scene_event(self, datapoint) -> None:
        """Emit a ZHA event when a gang in scene mode is pressed."""
        command = SCENE_DP_TO_COMMAND.get(datapoint.dp)
        if command is None:
            return

        self.listener_event(
            ZHA_SEND_EVENT,
            command,
            {
                COMMAND: command,
                "button": BUTTONS[datapoint.dp],
                "press_type": SHORT_PRESS,
                "value": datapoint.data.payload,
            },
        )

    async def write_attributes(
        self,
        attributes: dict[str | int | foundation.ZCLAttributeDef, Any],
        manufacturer: int | UndefinedType | None = UNDEFINED,
        **kwargs,
    ) -> list[list[foundation.WriteAttributesStatusRecord]]:
        """Silently ignore relay writes when the corresponding gang is in scene mode."""
        allowed_attributes = {}

        for attr, value in attributes.items():
            attr_name = self._attribute_name(attr, self.attributes)
            mode_attr = RELAY_ATTR_TO_MODE_ATTR.get(attr_name)

            if mode_attr and _is_scene_mode(self.get(mode_attr)):
                self.debug(
                    "Ignoring %s write because %s is scene",
                    attr_name,
                    mode_attr,
                )
                continue

            allowed_attributes[attr] = value

        if allowed_attributes:
            return await super().write_attributes(
                allowed_attributes,
                manufacturer=manufacturer,
                **kwargs,
            )

        return [[foundation.WriteAttributesStatusRecord(foundation.Status.SUCCESS)]]


def _add_switch_mode(builder: TuyaQuirkBuilder, gang: int) -> None:
    """Expose switch/scene mode as a select plus a scene-mode binary sensor."""
    mode_dp = 17 + gang
    mode_attr = f"switch_mode_l{gang}"
    scene_mode_attr = f"scene_mode_l{gang}"

    builder.tuya_attribute(
        dp_id=mode_dp,
        attribute_name=mode_attr,
        type=SceneSwitchMode,
        access=foundation.ZCLAttributeAccess.Read
        | foundation.ZCLAttributeAccess.Write,
    )
    builder.tuya_attribute(
        dp_id=0x70 + gang,
        attribute_name=scene_mode_attr,
        type=t.Bool,
        access=foundation.ZCLAttributeAccess.Read
        | foundation.ZCLAttributeAccess.Report,
    )
    builder.tuya_dp_multi(
        mode_dp,
        [
            DPToAttributeMapping(
                TuyaMCUCluster.ep_attribute,
                mode_attr,
                converter=_as_switch_mode,
            ),
            DPToAttributeMapping(
                TuyaMCUCluster.ep_attribute,
                scene_mode_attr,
                converter=_is_scene_mode,
            ),
        ],
    )
    builder.enum(
        mode_attr,
        SceneSwitchMode,
        TUYA_CLUSTER_ID,
        entity_type=EntityType.CONFIG,
        translation_key=mode_attr,
        fallback_name=f"L{gang} switch mode",
    )
    builder.binary_sensor(
        scene_mode_attr,
        TUYA_CLUSTER_ID,
        entity_type=EntityType.DIAGNOSTIC,
        translation_key=scene_mode_attr,
        fallback_name=f"L{gang} scene mode",
    )


def _builder(manufacturer: str, gang_count: int) -> TuyaQuirkBuilder:
    """Build the switch/scene quirk for one TS0601 variant."""
    builder = TuyaQuirkBuilder(manufacturer, "TS0601")

    for gang in range(1, gang_count + 1):
        builder.tuya_dp_multi(
            gang,
            [],
            dp_handler="_handle_scene_event",
        )
        builder.tuya_switch(
            dp_id=23 + gang,
            attribute_name=f"state_l{gang}",
            entity_type=EntityType.STANDARD,
            translation_key=f"state_l{gang}",
            fallback_name=f"L{gang}",
        )
        _add_switch_mode(builder, gang)

    return builder.skip_configuration().tuya_enchantment(data_query_spell=True)


for _manufacturer, _gang_count in SCENE_SWITCH_SIGNATURES:
    _builder(_manufacturer, _gang_count).device_automation_triggers(
        {
            (SHORT_PRESS, BUTTONS[gang]): {
                COMMAND: SCENE_DP_TO_COMMAND[gang],
                CLUSTER_ID: TUYA_CLUSTER_ID,
            }
            for gang in range(1, _gang_count + 1)
        }
    ).add_to_registry(replacement_cluster=SceneSwitchTuyaCluster)
