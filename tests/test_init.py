"""Setup / unload / reauth-trigger tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pysilverline import CannotConnect, InvalidAuth
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    assert init_integration.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_connect_failure(
    hass: HomeAssistant, mock_client_factory, config_entry: MockConfigEntry
) -> None:
    mock_client_factory.connect.side_effect = CannotConnect("offline")
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_triggers_reauth_on_invalid_key(
    hass: HomeAssistant, mock_client_factory, config_entry: MockConfigEntry
) -> None:
    mock_client_factory.get_status = AsyncMock(side_effect=InvalidAuth("bad"))
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(config_entry.domain)
    assert any(flow["context"].get("source") == "reauth" for flow in flows)
