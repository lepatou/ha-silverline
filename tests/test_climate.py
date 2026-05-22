"""Climate state machine: DP-1/DP-4 ↔ HVAC mode + preset."""

from __future__ import annotations

import asyncio

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


# ---------------------------------------------------------------------------
# Mode-aware setpoint range (Heat 15-40, Cool 8-28, Auto 8-40)
# ---------------------------------------------------------------------------


async def test_min_max_temp_for_heat_mode(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Heat", "2": 27, "3": 28})
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["min_temp"] == 15
    assert state.attributes["max_temp"] == 40


async def test_min_max_temp_for_cool_mode(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Cool", "2": 18, "3": 22})
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["min_temp"] == 8
    assert state.attributes["max_temp"] == 28


async def test_min_max_temp_for_auto_mode(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Auto", "2": 26, "3": 27})
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["min_temp"] == 8
    assert state.attributes["max_temp"] == 40


async def test_min_max_temp_when_off_uses_last_direction(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    """When OFF, the slider bounds come from _last_direction so the UI
    still shows a sensible range matching the user's last active mode."""
    coordinator = init_integration.runtime_data
    # Start in Cool, then power off — _last_direction should be Cool.
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Cool", "2": 20, "3": 22})
    )
    await hass.async_block_till_done()
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": False, "4": "Cool", "3": 22})
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == HVACMode.OFF
    assert state.attributes["min_temp"] == 8
    assert state.attributes["max_temp"] == 28


async def test_set_temperature_out_of_range_in_cool_blocked_by_ha(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    """HA's climate service validates target against our mode-aware
    min_temp/max_temp BEFORE we run, so a 35°C write while in Cool
    (max 28) is rejected at the service layer — DP 2 stays untouched."""
    coordinator = init_integration.runtime_data
    coordinator.async_set_updated_data(
        DeviceState.from_dps({"1": True, "4": "Cool", "2": 25, "3": 26})
    )
    await hass.async_block_till_done()
    mock_client_factory.set_multiple.reset_mock()

    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 35},
            blocking=True,
        )
    # HA uses its own translation key for the standard temp range check.
    assert exc.value.translation_key == "temp_out_of_range"
    mock_client_factory.set_multiple.assert_not_called()


async def test_set_temperature_below_heat_min_blocked_by_ha(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    """Writing 10°C while in Heat (min 15) is blocked at HA's service
    validator, again driven by our mode-aware min_temp."""
    # init_integration starts in Heat mode
    mock_client_factory.set_multiple.reset_mock()
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 10},
            blocking=True,
        )
    assert exc.value.translation_key == "temp_out_of_range"
    mock_client_factory.set_multiple.assert_not_called()


# ---------------------------------------------------------------------------
# Mode-transition settle: the 0.7s sleep after non-OFF set_hvac_mode
# ---------------------------------------------------------------------------


async def test_set_hvac_mode_sleeps_after_non_off_write(
    hass: HomeAssistant, mock_client_factory, init_integration, monkeypatch
) -> None:
    """async_set_hvac_mode should sleep _MODE_TRANSITION_SETTLE after
    a non-OFF write so the device's per-mode-memory restore push
    lands before any chained set_temperature races with it."""
    import custom_components.poolex_silverline.climate as climate_mod

    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(climate_mod.asyncio, "sleep", fake_sleep)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    assert climate_mod._MODE_TRANSITION_SETTLE in recorded


async def test_set_hvac_off_does_not_sleep(
    hass: HomeAssistant, mock_client_factory, init_integration, monkeypatch
) -> None:
    """async_set_hvac_mode(OFF) doesn't trigger the per-mode-memory restore
    so no settle wait is needed — keep the call snappy."""
    import custom_components.poolex_silverline.climate as climate_mod

    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(climate_mod.asyncio, "sleep", fake_sleep)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    assert climate_mod._MODE_TRANSITION_SETTLE not in recorded
