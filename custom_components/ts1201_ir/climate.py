"""Native daily AC control, backed exclusively by the matched quirk codebook."""

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .entity import Ts1201Entity, async_setup_entities


class Ts1201Climate(Ts1201Entity, ClimateEntity):
    """An assumed-state thermostat with no fabricated room temperature."""

    PLATFORM = "climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_assumed_state = True
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, ieee):
        super().__init__(coordinator, ieee, "ac_climate", "空调")

    @property
    def control(self):
        return self.coordinator.climate_snapshot(self.ieee)

    @property
    def available(self):
        return super().available and bool(self.control.get("available"))

    @property
    def supported_features(self):
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        temperature = self.control.get("temperature", {})
        if temperature.get("applicable") and temperature.get("step") is not None:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if self.control.get("fans") and self.control.get("mode_constraints", {}).get(
            "fanControllable", True
        ):
            features |= ClimateEntityFeature.FAN_MODE
        return features

    @property
    def hvac_mode(self):
        state = self.control.get("estimated")
        if not state:
            return None
        return HVACMode(state["mode"]) if state["power"] else HVACMode.OFF

    @property
    def hvac_modes(self):
        return [HVACMode(mode) for mode in self.control.get("modes", [])]

    @property
    def current_temperature(self):
        return None

    @property
    def hvac_action(self):
        return None

    @property
    def target_temperature(self):
        if not self.control.get("temperature", {}).get("applicable"):
            return None
        return (self.control.get("desired") or {}).get("temperature")

    @property
    def target_temperature_step(self):
        temperature = self.control.get("temperature", {})
        return temperature.get("step") if temperature.get("applicable") else None

    @property
    def min_temp(self):
        return self.control.get("temperature", {}).get("min")

    @property
    def max_temp(self):
        return self.control.get("temperature", {}).get("max")

    @property
    def fan_mode(self):
        return (self.control.get("desired") or {}).get("fan")

    @property
    def fan_modes(self):
        return self.control.get("fans", [])

    @property
    def extra_state_attributes(self):
        return {
            "state_source": "红外命令估计，非空调实际反馈",
            "codebook_id": self.control.get("codebook_id"),
            "control_status": self.control.get("status", ""),
            "pending": self.control.get("pending", False),
            "requested": self.control.get("requested"),
            "estimate_stale": self.control.get("estimate_stale", False),
            "temperature_applicable": self.control.get("temperature", {}).get(
                "applicable", False
            ),
            "stored_temperature": (self.control.get("desired") or {}).get(
                "temperature"
            ),
        }

    async def async_set_hvac_mode(self, hvac_mode):
        await self.coordinator.async_climate_action(self.ieee, {"mode": str(hvac_mode)})

    async def async_set_temperature(self, **kwargs):
        patch = {}
        if ATTR_TEMPERATURE in kwargs:
            patch["temperature"] = kwargs[ATTR_TEMPERATURE]
        if "hvac_mode" in kwargs:
            patch["mode"] = str(kwargs["hvac_mode"])
        if not patch:
            raise HomeAssistantError("请指定温度或工作模式")
        await self.coordinator.async_climate_action(self.ieee, patch)

    async def async_set_fan_mode(self, fan_mode):
        await self.coordinator.async_climate_action(self.ieee, {"fan": fan_mode})

    async def async_turn_on(self):
        await self.coordinator.async_climate_action(self.ieee, {"power": True})

    async def async_turn_off(self):
        await self.coordinator.async_climate_action(self.ieee, {"power": False})


def entities(coordinator):
    for ieee in coordinator.data:
        if coordinator.climate_snapshot(ieee).get("supported"):
            yield Ts1201Climate(coordinator, ieee)


async def async_setup_entry(hass, entry, async_add_entities):
    await async_setup_entities(hass, entry, async_add_entities, entities)
