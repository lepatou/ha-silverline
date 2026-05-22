"""Sensor tests — value_fn results, fault decoding, availability."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pysilverline import DeviceState


async def test_diagnostic_sensors_populate(
    hass: HomeAssistant, init_integration
) -> None:
    state = hass.states.get("sensor.pool_heatpump_water_inlet_temperature")
    assert state is not None
    assert state.state == "26"

    state = hass.states.get("sensor.pool_heatpump_water_outlet_temperature")
    assert state is not None
    assert state.state == "28"

    state = hass.states.get("sensor.pool_heatpump_compressor_actual_frequency")
    assert state is not None
    assert state.state == "63"


async def test_fault_code_decoded_to_enum_state(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data

    coordinator.async_set_updated_data(DeviceState.from_dps({"13": 0}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_heatpump_fault_code").state == "none"

    coordinator.async_set_updated_data(DeviceState.from_dps({"13": 1}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_heatpump_fault_code").state == "E03"

    coordinator.async_set_updated_data(DeviceState.from_dps({"13": 2}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_heatpump_fault_code").state == "E04"

    coordinator.async_set_updated_data(DeviceState.from_dps({"13": 1 << 25}))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pool_heatpump_fault_code").state == "unknown"


async def test_sensor_unavailable_when_dp_missing(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    """If the firmware doesn't expose DPs 101–110, those sensors must
    surface as unavailable rather than blowing up the integration."""
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Heat", "3": 25, "13": 0})
    )
    await hass.async_block_till_done()
    state = hass.states.get("sensor.pool_heatpump_water_inlet_temperature")
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
