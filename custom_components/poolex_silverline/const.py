"""Constants for the Poolex Silverline integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "poolex_silverline"
MANUFACTURER: Final = "Poolex"
MODEL: Final = "Silverline Inverter (PC-SLP090N)"

CONF_DEVICE_ID: Final = "device_id"
CONF_LOCAL_KEY: Final = "local_key"

DEFAULT_PORT: Final = 6668
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds; WBR3 reboots if polled <8s

PRESET_BOOST: Final = "boost"
PRESET_ECO: Final = "eco"

# DP-4 enum suffix mapping helpers used by the climate state machine.
HEAT_PREFIX_TO_PRESET: Final = {
    "Heat": "none",
    "BoostHeat": PRESET_BOOST,
    "SilentHeat": PRESET_ECO,
}
COOL_PREFIX_TO_PRESET: Final = {
    "Cool": "none",
    "BoostCool": PRESET_BOOST,
    "SilentCool": PRESET_ECO,
}
PRESET_TO_HEAT_DP: Final = {
    "none": "Heat",
    PRESET_BOOST: "BoostHeat",
    PRESET_ECO: "SilentHeat",
}
PRESET_TO_COOL_DP: Final = {
    "none": "Cool",
    PRESET_BOOST: "BoostCool",
    PRESET_ECO: "SilentCool",
}

# Mode-specific setpoint ranges. The wire-layer pysilverline.const.TEMP_MIN /
# TEMP_MAX (8 / 40) is the union schema guard; these are what the device
# actually accepts per mode, verified live against a PC-SLP090N. Writing
# outside the per-mode range is server-side clamped — we reject up-front so
# the UI's target_temperature can't silently move.
HEAT_TEMP_MIN: Final = 15
HEAT_TEMP_MAX: Final = 40
COOL_TEMP_MIN: Final = 8
COOL_TEMP_MAX: Final = 28
AUTO_TEMP_MIN: Final = 8
AUTO_TEMP_MAX: Final = 40
