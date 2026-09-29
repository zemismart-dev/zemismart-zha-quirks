"""Status and count only; no raw infrared codes in HA sensor state."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import Ts1201Entity, async_setup_entities


class KeySensor(Ts1201Entity, SensorEntity):
    PLATFORM = "sensor"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, ieee, kind):
        super().__init__(
            coordinator,
            ieee,
            f"key_{kind}",
            "按键库状态" if kind == "status" else "已保存按键数量",
        )
        self.kind = kind
        if kind == "status":
            self._attr_entity_category = None

    @property
    def native_value(self):
        return self.snapshot.get(self.kind, "" if self.kind == "status" else 0)

    @property
    def extra_state_attributes(self):
        if self.kind != "status":
            return None
        return {
            name: self.snapshot.get(name)
            for name in (
                "revision",
                "learning",
                "busy",
                "pending_valid",
                "pending_expires_at",
                "can_undo",
            )
        }


class ClimateStatusSensor(Ts1201Entity, SensorEntity):
    """Show asynchronous IR completion/failure without opening climate attributes."""

    PLATFORM = "sensor"

    def __init__(self, coordinator, ieee):
        super().__init__(coordinator, ieee, "ac_control_status", "空调控制状态")

    @property
    def control(self):
        return self.coordinator.climate_snapshot(self.ieee)

    @property
    def available(self):
        return super().available and bool(self.control.get("available"))

    @property
    def native_value(self):
        return self.control.get("status")


def entities(coordinator):
    for ieee in coordinator.data:
        for kind in ("status", "count"):
            yield KeySensor(coordinator, ieee, kind)
        if coordinator.climate_snapshot(ieee).get("supported"):
            yield ClimateStatusSensor(coordinator, ieee)


async def async_setup_entry(hass, entry, async_add_entities):
    await async_setup_entities(
        hass,
        entry,
        async_add_entities,
        entities,
    )
