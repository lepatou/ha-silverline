"""Exceptions raised by pysilverline."""

from __future__ import annotations


class SilverlineError(Exception):
    """Base error."""


class CannotConnect(SilverlineError):
    """Network or transport-level failure."""


class InvalidAuth(SilverlineError):
    """The local_key was rejected by the device."""


class ProtocolError(SilverlineError):
    """The frame was malformed or out of spec."""


class DeviceLocked(SilverlineError):
    """The device refused the command (Tuya error code 0xFF)."""
