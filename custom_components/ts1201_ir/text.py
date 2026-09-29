"""Native editable name field for named IR learning."""

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.helpers.entity import EntityCategory

from .entity import Ts1201Entity, async_setup_entities


class KeyNameText(Ts1201Entity, TextEntity):
    PLATFORM = "text"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 0
    _attr_native_max = 48
    _attr_mode = TextMode.TEXT

    def __init__(self, coordinator, ieee):
        super().__init__(coordinator, ieee, "key_name", "按键名称")

    @property
    def native_value(self):
        return self.snapshot.get("name", "")

    async def async_set_value(self, value):
        await self.async_action("name", value)


async def async_setup_entry(hass, entry, async_add_entities):
    await async_setup_entities(
        hass,
        entry,
        async_add_entities,
        lambda coordinator: [
            KeyNameText(coordinator, ieee) for ieee in coordinator.data
        ],
    )
