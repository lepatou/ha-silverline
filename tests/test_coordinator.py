"""Coordinator behavior: push, refresh, error mapping."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pysilverline import CannotConnect, DeviceState, InvalidAuth
from pytest_homeassistant_custom_component.common import async_fire_time_changed


async def test_push_callback_updates_state(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    listeners = mock_client_factory.listeners
    assert listeners, "coordinator should have registered exactly one listener"

    new_state = DeviceState.from_dps({"1": True, "3": 35, "4": "BoostHeat", "13": 0})
    listeners[0](new_state)
    await hass.async_block_till_done()
    assert coordinator.data is new_state


async def test_invalid_auth_during_poll_marks_auth_failed(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    mock_client_factory.get_status = AsyncMock(side_effect=InvalidAuth("rotated"))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(init_integration.domain)
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


async def test_cannot_connect_during_poll_keeps_entry_loaded(
    hass: HomeAssistant, mock_client_factory, init_integration
) -> None:
    mock_client_factory.get_status = AsyncMock(side_effect=CannotConnect("timeout"))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
    await hass.async_block_till_done()
    coordinator = init_integration.runtime_data
    assert coordinator.last_update_success is False
