"""Shared base entity for Poolex Silverline platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SilverlineCoordinator


class SilverlineEntity(CoordinatorEntity[SilverlineCoordinator]):
    """Base entity that wires up DeviceInfo from coordinator state."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SilverlineCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.device_info.device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="Pool Heatpump",
            sw_version=coordinator.device_info.firmware,
            serial_number=device_id,
        )
