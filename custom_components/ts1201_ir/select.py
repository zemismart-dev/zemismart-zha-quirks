"""Selection of a quirk-owned key by its visible name."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory

from .const import EMPTY_SELECTION
from .entity import Ts1201Entity, async_setup_entities


class KeySelect(Ts1201Entity, SelectEntity):
    PLATFORM = "select"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, ieee):
        super().__init__(coordinator, ieee, "key_selected", "已保存按键")

    @property
    def options(self):
        return [key["name"] for key in self.snapshot.get("keys", [])] or [
            EMPTY_SELECTION
        ]

    @property
    def current_option(self):
        keys = self.snapshot.get("keys", [])
        return next(
            (
                key["name"]
                for key in keys
                if key["id"] == self.snapshot.get("selected_id")
            ),
            EMPTY_SELECTION if not keys else None,
        )

    async def async_select_option(self, option):
        # Resolve against a fresh snapshot, never an old cached label->ID map.
        await self.coordinator.async_refresh()
        keys = self.snapshot.get("keys", [])
        match = next((key for key in keys if key["name"] == option), None)
        if match:
            await self.async_action("selected", match["id"])
        elif not keys and option == EMPTY_SELECTION:
            await self.async_action("selected", None)
        else:
            raise HomeAssistantError("此按键名称已变化或不存在，请重新选择")


class ExactTemperatureSelect(Ts1201Entity, SelectEntity):
    """Offer actual source temperatures when a uniform thermostat step is invalid."""

    PLATFORM = "select"

    def __init__(self, coordinator, ieee):
        super().__init__(
            coordinator, ieee, "ac_temperature_choice", "空调温度选择（℃）"
        )

    @property
    def control(self):
        return self.coordinator.climate_snapshot(self.ieee)

    @property
    def available(self):
        temperature = self.control.get("temperature", {})
        return (
            super().available
            and bool(self.control.get("available"))
            and bool(temperature.get("applicable"))
            and temperature.get("step") is None
        )

    @property
    def options(self):
        return [
            str(value)
            for value in self.control.get("temperature", {}).get("values", [])
        ]

    @property
    def current_option(self):
        value = (self.control.get("desired") or {}).get("temperature")
        return next(
            (
                str(option)
                for option in self.control.get("temperature", {}).get("values", [])
                if value is not None and option == value
            ),
            None,
        )

    async def async_select_option(self, option):
        await self.coordinator.async_refresh()
        if not self.available:
            raise HomeAssistantError("当前模式无需离散温度选择，请刷新空调控制")
        values = self.control.get("temperature", {}).get("values", [])
        value = next((value for value in values if str(value) == option), None)
        if value is None:
            raise HomeAssistantError("此模式不支持该温度，请选择列表中的精确温度")
        await self.coordinator.async_climate_action(self.ieee, {"temperature": value})


def entities(coordinator):
    for ieee in coordinator.data:
        if coordinator.snapshot(ieee).get("keys"):
            yield KeySelect(coordinator, ieee)
        control = coordinator.climate_snapshot(ieee)
        temperature = control.get("temperature", {})
        if (
            control.get("supported")
            and temperature.get("applicable")
            and temperature.get("step") is None
            and temperature.get("values")
        ):
            yield ExactTemperatureSelect(coordinator, ieee)


async def async_setup_entry(hass, entry, async_add_entities):
    await async_setup_entities(
        hass,
        entry,
        async_add_entities,
        entities,
        managed_ids=lambda coordinator: {
            f"{ieee}_key_selected" for ieee in coordinator.data
        },
        platform_domain="select",
    )
