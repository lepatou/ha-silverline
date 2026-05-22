"""Binary sensor tests — water pump and decoded fault bits."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pysilverline import DeviceState


async def test_water_pump(hass: HomeAssistant, init_integration) -> None:
    assert hass.states.get("binary_sensor.pool_heatpump_water_pump").state == STATE_ON


async def test_fault_bits(hass: HomeAssistant, init_integration) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(DeviceState.from_dps({"13": 0b00010101}))
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.pool_heatpump_water_flow_fault").state == STATE_ON
    assert hass.states.get("binary_sensor.pool_heatpump_antifreeze_fault").state == STATE_OFF
    assert hass.states.get("binary_sensor.pool_heatpump_high_pressure_fault").state == STATE_ON
    assert hass.states.get("binary_sensor.pool_heatpump_low_pressure_fault").state == STATE_OFF
    assert hass.states.get("binary_sensor.pool_heatpump_communication_fault").state == STATE_ON
