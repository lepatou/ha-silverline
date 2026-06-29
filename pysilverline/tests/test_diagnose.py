"""Tests for the diagnostic report builder (pure functions, no network)."""

from __future__ import annotations

from typing import Any

from pysilverline import diagnose

HOST = "poolheatpump.secret.example"
DEVICE_ID = "bf77SECRETdeviceid32"
LOCAL_KEY = "SECRETlocalkey16"


def _sample(**over: Any) -> dict[str, Any]:
    """A representative ``gather()`` result with secrets embedded everywhere
    they realistically appear: target fields, discovery, an error message and a
    log line (the host-leak surfaces the tool exists to avoid)."""
    base: dict[str, Any] = {
        "versions": {"pysilverline": "0.4.9", "python": "3.14.5", "platform": "Linux"},
        "target": {"host": HOST, "device_id": DEVICE_ID, "pinned_version": None},
        "discovery": [
            {
                "ip": "10.2.1.98",
                "device_id": DEVICE_ID,
                "product_key": "3bhylhz5zhogklel",
                "version": "3.3",
            }
        ],
        "connection": {"detected_version": "3.3", "connected": True},
        "read": {
            "supported_dps": ["1", "2", "3", "4", "13"],
            "raw": {"1": False, "2": 28, "3": 31, "4": "Auto", "13": 0},
            "decoded": {"power": False, "temp_set": 28, "mode": "Auto"},
        },
        "write_probe": None,
        "error": None,
        "log": [f"DEBUG pysilverline.session: v3.5 probe failed for {HOST}; next"],
    }
    base.update(over)
    return base


def test_redact_masks_identifiers_keeps_dp_map_and_product_key() -> None:
    report = diagnose.redact(_sample())
    assert report["target"]["host"] == diagnose._REDACTED
    assert report["target"]["device_id"] == diagnose._REDACTED
    # Discovery: ip + device id masked, productKey + version kept.
    disc = report["discovery"][0]
    assert disc["ip"] == diagnose._REDACTED
    assert disc["device_id"] == diagnose._REDACTED
    assert disc["product_key"] == "3bhylhz5zhogklel"
    # The device id must not leak through the rendered table either.
    assert DEVICE_ID not in diagnose.format_markdown(report)
    # The DP map is the whole point — never redacted.
    assert report["read"]["raw"] == {"1": False, "2": 28, "3": 31, "4": "Auto", "13": 0}


def test_redact_scrubs_host_from_log_lines() -> None:
    report = diagnose.redact(_sample())
    joined = "\n".join(report["log"])
    assert HOST not in joined
    assert "<host>" in joined


def test_redact_scrubs_host_from_error_message() -> None:
    # pysilverline CannotConnect embeds the host; a raw paste would leak it.
    sample = _sample(
        read=None,
        error={"type": "CannotConnect", "message": f"cannot connect to {HOST}:6668"},
    )
    report = diagnose.redact(sample)
    assert HOST not in report["error"]["message"]
    assert report["error"]["type"] == "CannotConnect"


def test_format_markdown_never_leaks_secrets() -> None:
    sample = _sample(
        error={"type": "CannotConnect", "message": f"cannot connect to {HOST}"},
    )
    text = diagnose.format_markdown(diagnose.redact(sample))
    for secret in (HOST, DEVICE_ID, LOCAL_KEY):
        assert secret not in text
    # Useful, non-secret content survives.
    assert "3bhylhz5zhogklel" in text
    assert "Detected protocol version: `3.3`" in text
    assert '"4": "Auto"' in text


def test_format_markdown_renders_write_probe_rejection() -> None:
    sample = _sample(
        write_probe={
            "dp": 2,
            "value_before": 28,
            "result": "rejected",
            "error_type": "SilverlineError",
            "error_message": "CONTROL failed retcode=0x01000000",
        }
    )
    text = diagnose.format_markdown(diagnose.redact(sample))
    assert "Write probe" in text
    assert "rejected" in text
    assert "0x01000000" in text  # the issue-#7 signal must survive to the report


def test_sanitize_longest_secret_first() -> None:
    # A value that contains a shorter secret must still be fully masked.
    secrets = {"host": "abc.example", "device_id": "abc"}
    out = diagnose._sanitize("connect abc.example failed", secrets)
    assert "abc.example" not in out
    assert out == "connect <host> failed"


def test_no_redact_passthrough_keeps_raw_dict_identity() -> None:
    # --no-redact path: format the un-redacted gather() dict directly.
    sample = _sample()
    text = diagnose.format_markdown(sample)
    assert HOST in text  # not redacted in this mode


# --- interactive prompts -------------------------------------------------


def _scripted(answers: list[str]) -> Any:
    """A fake ``input`` that returns queued answers in order."""
    it = iter(answers)
    return lambda _prompt="": next(it)


def _empty_args() -> Any:
    import argparse

    return argparse.Namespace(
        host=None,
        device_id=None,
        local_key=None,
        version=None,
        probe_write=False,
        discovery_timeout=6.0,
    )


def test_interactive_device_picker_prefills_host_and_id() -> None:
    from pysilverline.discovery import DiscoveryInfo

    discovered = [
        DiscoveryInfo(device_id="DEV123", ip="10.0.0.9", version="3.5",
                      product_key="pk")
    ]
    # Pick device 1, enter a valid key, accept auto version, decline write probe.
    answers = _scripted(["1", "0123456789abcdef", "", "n"])
    params = diagnose._collect_interactive(
        _empty_args(), discovered, input_fn=answers
    )
    assert params["host"] == "10.0.0.9"
    assert params["device_id"] == "DEV123"
    assert params["version"] is None  # "auto"
    assert params["probe_write"] is False
    assert params["local_key"] == "0123456789abcdef"


def test_interactive_key_validation_reprompts() -> None:
    # Manual entry (no discovery): short key rejected, then a valid one accepted.
    answers = _scripted(
        ["192.168.1.5", "DEVID", "tooshort", "0123456789abcdef", "auto", "y"]
    )
    params = diagnose._collect_interactive(_empty_args(), [], input_fn=answers)
    assert params["host"] == "192.168.1.5"
    assert params["device_id"] == "DEVID"
    assert params["local_key"] == "0123456789abcdef"
    assert params["probe_write"] is True


def test_prompt_yes_no_default_and_parsing() -> None:
    assert diagnose._prompt_yes_no("?", default=True, input_fn=_scripted([""])) is True
    assert diagnose._prompt_yes_no("?", default=False, input_fn=_scripted([""])) is False
    assert diagnose._prompt_yes_no("?", input_fn=_scripted(["yes"])) is True
