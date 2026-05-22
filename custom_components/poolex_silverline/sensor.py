"""Diagnostic sensors for the Poolex Silverline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfFrequency,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pysilverline import DeviceState, const as tuya_const

from .coordinator import SilverlineConfigEntry, SilverlineCoordinator
from .entity import SilverlineEntity

PARALLEL_UPDATES = 0

_FAULT_OPTIONS: list[str] = ["none", *tuya_const.FAULT_BIT_NAMES.values(), "unknown"]


def _decode_fault(raw: int | None) -> str | None:
    if raw is None:
        return None
    if raw == 0:
        return "none"
    for bit, name in tuya_const.FAULT_BIT_NAMES.items():
        if raw & (1 << bit):
            return name
    return "unknown"


@dataclass(frozen=True, kw_only=True)
class SilverlineSensorDescription(SensorEntityDescription):
    """Sensor description that pulls a value from DeviceState."""

    value_fn: Callable[[DeviceState], float | int | str | None]


SENSORS: tuple[SilverlineSensorDescription, ...] = (
    SilverlineSensorDescription(
        key="exhaust_temperature",
        translation_key="exhaust_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.exhaust_temp,
    ),
    SilverlineSensorDescription(
        key="return_temperature",
        translation_key="return_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.return_temp,
    ),
    SilverlineSensorDescription(
        key="coil_temperature",
        translation_key="coil_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.coil_temp,
    ),
    SilverlineSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.ambient_temp,
    ),
    SilverlineSensorDescription(
        key="inlet_temperature",
        translation_key="inlet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.inlet_temp,
    ),
    SilverlineSensorDescription(
        key="outlet_temperature",
        translation_key="outlet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.outlet_temp,
    ),
    SilverlineSensorDescription(
        key="target_frequency",
        translation_key="target_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.target_frequency,
    ),
    SilverlineSensorDescription(
        key="actual_frequency",
        translation_key="actual_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.actual_frequency,
    ),
    SilverlineSensorDescription(
        key="eev_steps",
        translation_key="eev_steps",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="steps",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.eev_steps,
    ),
    SilverlineSensorDescription(
        key="fan_speed",
        translation_key="fan_speed",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.fan_speed,
    ),
    SilverlineSensorDescription(
        key="fault_code",
        translation_key="fault_code",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=_FAULT_OPTIONS,
        value_fn=lambda d: _decode_fault(d.fault),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SilverlineConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SilverlineSensor(coordinator, description) for description in SENSORS
    )


class SilverlineSensor(SilverlineEntity, SensorEntity):
    entity_description: SilverlineSensorDescription

    def __init__(
        self,
        coordinator: SilverlineCoordinator,
        description: SilverlineSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.device_info.device_id}_{description.key}"
        )

    @property
    def native_value(self) -> float | int | str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        return self.entity_description.value_fn(self.coordinator.data) is not None
