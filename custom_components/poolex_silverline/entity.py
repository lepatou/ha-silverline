"""Shared base entity for Poolex Silverline platforms."""

from __future__ import annotations

from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pysilverline import DeviceState

from .const import COOL_PREFIX_TO_PRESET, DOMAIN, HEAT_PREFIX_TO_PRESET, MANUFACTURER, MODEL
from .coordinator import SilverlineCoordinator


def _hvac_mode_from_state(state: DeviceState) -> HVACMode | None:
    """Mirror SilverlineClimate.hvac_mode without needing the entity instance.

    Lives here so non-climate consumers (runtime accumulator, diagnostics)
    can resolve the same hvac_action without re-implementing the DP-4 ->
    HVACMode mapping.
    """
    if state.power is None:
        return None
    if not state.power:
        return HVACMode.OFF
    mode = state.mode or ""
    if mode == "Auto":
        return HVACMode.HEAT_COOL
    if mode in HEAT_PREFIX_TO_PRESET:
        return HVACMode.HEAT
    if mode in COOL_PREFIX_TO_PRESET:
        return HVACMode.COOL
    return None


def compute_hvac_action(
    state: DeviceState, last_direction: HVACMode | None = None
) -> HVACAction | None:
    """Resolve the active hvac_action from a DeviceState.

    `last_direction` is accepted for API parity with the climate entity's
    own bookkeeping, but the action itself is determined entirely from the
    live state — power flag, mode prefix, compressor frequency (DP 108
    when present), and the temp_current/temp_set delta as a fallback.
    """
    del last_direction  # currently unused — see docstring
    if state.power is None:
        return None
    if not state.power:
        return HVACAction.OFF
    mode = _hvac_mode_from_state(state)
    freq = state.actual_frequency
    active = freq > 0 if isinstance(freq, int) else None
    current = state.temp_current
    target = state.temp_set

    def _heat_or_idle() -> HVACAction:
        if active is True:
            return HVACAction.HEATING
        if active is False:
            return HVACAction.IDLE
        if current is not None and target is not None:
            return HVACAction.HEATING if current < target else HVACAction.IDLE
        return HVACAction.IDLE

    def _cool_or_idle() -> HVACAction:
        if active is True:
            return HVACAction.COOLING
        if active is False:
            return HVACAction.IDLE
        if current is not None and target is not None:
            return HVACAction.COOLING if current > target else HVACAction.IDLE
        return HVACAction.IDLE

    if mode == HVACMode.HEAT:
        return _heat_or_idle()
    if mode == HVACMode.COOL:
        return _cool_or_idle()
    if mode == HVACMode.HEAT_COOL:
        if current is None or target is None:
            return HVACAction.IDLE
        if active is False:
            return HVACAction.IDLE
        if current < target:
            return HVACAction.HEATING
        if current > target:
            return HVACAction.COOLING
        return HVACAction.IDLE
    return HVACAction.IDLE


class SilverlineEntity(CoordinatorEntity[SilverlineCoordinator]):
    """Base entity that wires up DeviceInfo from coordinator state."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SilverlineCoordinator) -> None:
        super().__init__(coordinator)
        device_id = coordinator.device_info.device_id
        host = coordinator.config_entry.data[CONF_HOST]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="Pool Heatpump",
            sw_version=coordinator.device_info.firmware,
            serial_number=device_id,
            configuration_url=f"http://{host}/",
        )
