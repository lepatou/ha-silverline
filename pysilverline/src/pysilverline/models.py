"""Typed data models for device state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import const


@dataclass(slots=True, kw_only=True, frozen=True)
class DeviceInfo:
    """Static device identity. Tuya v3.3 does not return a model string;
    fields are populated from the config entry plus what we infer."""

    device_id: str
    firmware: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class DeviceState:
    """Snapshot of all known DPs at a point in time. Missing DPs are None."""

    power: bool | None = None
    temp_set: int | None = None
    temp_current: int | None = None
    mode: str | None = None
    fault: int | None = None
    exhaust_temp: int | None = None
    return_temp: int | None = None
    coil_temp: int | None = None
    ambient_temp: int | None = None
    inlet_temp: int | None = None
    outlet_temp: int | None = None
    target_frequency: int | None = None
    actual_frequency: int | None = None
    eev_steps: int | None = None
    fan_speed: int | None = None
    water_pump: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dps(cls, dps: dict[str, Any]) -> DeviceState:
        """Build a DeviceState from a Tuya `dps` mapping (string keys)."""

        def _get(dp: int) -> Any:
            return dps.get(str(dp))

        return cls(
            power=_get(const.DP_POWER),
            temp_set=_get(const.DP_TEMP_SET),
            temp_current=_get(const.DP_TEMP_CURRENT),
            mode=_get(const.DP_MODE),
            fault=_get(const.DP_FAULT),
            exhaust_temp=_get(const.DP_EXHAUST_TEMP),
            return_temp=_get(const.DP_RETURN_TEMP),
            coil_temp=_get(const.DP_COIL_TEMP),
            ambient_temp=_get(const.DP_AMBIENT_TEMP),
            inlet_temp=_get(const.DP_INLET_TEMP),
            outlet_temp=_get(const.DP_OUTLET_TEMP),
            target_frequency=_get(const.DP_TARGET_FREQUENCY),
            actual_frequency=_get(const.DP_ACTUAL_FREQUENCY),
            eev_steps=_get(const.DP_EEV_STEPS),
            fan_speed=_get(const.DP_FAN_SPEED),
            water_pump=_get(const.DP_WATER_PUMP),
            raw=dict(dps),
        )

    def merge(self, dps: dict[str, Any]) -> DeviceState:
        """Return a new state with `dps` overlaid onto the current `raw` dict."""

        merged = {**self.raw, **dps}
        return DeviceState.from_dps(merged)
