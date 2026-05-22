"""Climate state machine: DP-1/DP-4 ↔ HVAC mode + preset."""

from __future__ import annotations

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pysilverline import DeviceState

ENTITY_ID = "climate.pool_heatpump"


@pytest.mark.parametrize(
    "dps,expected_hvac,expected_preset",
    [
        ({"1": False, "4": "Heat"}, HVACMode.OFF, "none"),
        ({"1": True, "4": "Heat"}, HVACMode.HEAT, "none"),
        ({"1": True, "4": "BoostHeat"}, HVACMode.HEAT, "boost"),
        ({"1": True, "4": "SilentHeat"}, HVACMode.HEAT, "eco"),
        ({"1": True, "4": "Cool"}, HVACMode.COOL, "none"),
        ({"1": True, "4": "BoostCool"}, HVACMode.COOL, "boost"),
        ({"1": True, "4": "SilentCool"}, HVACMode.COOL, "eco"),
        ({"1": True, "4": "Auto"}, HVACMode.HEAT_COOL, "none"),
    ],
)
async def test_dp4_enum_decoded_to_hvac_and_preset(
    hass: HomeAssistant,
    mock_client_factory,
    init_integration,
    dps: dict[str, str | bool],
    expected_hvac: HVACMode,
    expected_preset: str,
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(DeviceState.from_dps({"3": 25, **dps}))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == expected_hvac
    assert state.attributes[ATTR_PRESET_MODE] == expected_preset


async def test_set_hvac_off_writes_dp1_false(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({1: False})


async def test_set_hvac_heat_writes_dp1_true_and_mode(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({1: True, 4: "Heat"})


async def test_set_hvac_heat_cool_writes_auto(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.HEAT_COOL},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({1: True, 4: "Auto"})


async def test_preset_boost_during_heat_writes_boostheat(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(DeviceState.from_dps({"1": True, "4": "Heat"}))
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: "boost"},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({4: "BoostHeat"})


async def test_preset_eco_during_cool_writes_silentcool(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(DeviceState.from_dps({"1": True, "4": "Cool"}))
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: "eco"},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({4: "SilentCool"})


async def test_preset_during_auto_raises(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(DeviceState.from_dps({"1": True, "4": "Auto"}))
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_PRESET_MODE: "boost"},
            blocking=True,
        )


async def test_set_temperature_rounds_to_int(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    """The entity rounds floats to an int before writing DP 2. Boundary
    behavior (mode-specific min/max) lives in its own test below."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 25.7},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({2: 26})

    # Both endpoints of the active mode (Heat: 15..40) are accepted.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 15},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({2: 15})

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 40},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({2: 40})


async def test_off_to_heat_preserves_last_preset(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data

    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "BoostHeat"})
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": False, "4": "BoostHeat"})
    )
    await hass.async_block_till_done()

    mock_client_factory.set_multiple.reset_mock()
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    mock_client_factory.set_multiple.assert_awaited_with({1: True, 4: "BoostHeat"})
