"""Management actions and stable-ID named infrared buttons."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .const import ACTION_NAMES
from .entity import Ts1201Entity, async_setup_entities


class KeyActionButton(Ts1201Entity, ButtonEntity):
    PLATFORM = "button"

    def __init__(self, coordinator, ieee, action):
        super().__init__(
            coordinator, ieee, f"key_action_{action}", ACTION_NAMES[action]
        )
        self.action = action
        self._attr_entity_category = None if action == "send" else EntityCategory.CONFIG

    async def async_press(self):
        await self.async_action(self.action)


class NamedKeyButton(Ts1201Entity, ButtonEntity):
    PLATFORM = "button"

    def __init__(self, coordinator, ieee, key_id):
        super().__init__(coordinator, ieee, f"key_{key_id}", None)
        self.key_id = key_id

    @property
    def name(self):
        return next(
            (
                key["name"]
                for key in self.snapshot.get("keys", [])
                if key["id"] == self.key_id
            ),
            "已删除按键",
        )

    async def async_press(self):
        await self.async_action("send", self.key_id)


def entities(coordinator):
    for ieee in coordinator.data:
        for action in coordinator.snapshot(ieee).get("relevant_actions", ["learn"]):
            yield KeyActionButton(coordinator, ieee, action)
        for key in coordinator.snapshot(ieee).get("keys", []):
            yield NamedKeyButton(coordinator, ieee, key["id"])


async def async_setup_entry(hass, entry, async_add_entities):
    await async_setup_entities(
        hass,
        entry,
        async_add_entities,
        entities,
        managed_ids=lambda coordinator: {
            f"{ieee}_key_action_{action}"
            for ieee in coordinator.data
            for action in ACTION_NAMES
        },
        platform_domain="button",
    )
