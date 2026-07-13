"""Tests for defensive WHB04 input packet handling."""

import importlib.util
import struct
import sys
import types
from pathlib import Path

import pytest

try:
    import hid  # noqa: F401
except ModuleNotFoundError:
    hid = types.ModuleType("hid")
    hid.Device = type("Device", (), {})
    hid.DeviceInfo = dict
    hid.enumerate = lambda: []
    sys.modules["hid"] = hid

MODULE_PATH = Path(__file__).parents[2] / "carveracontroller/addons/pendant/whb04.py"
SPEC = importlib.util.spec_from_file_location("whb04_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
whb04 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = whb04
SPEC.loader.exec_module(whb04)


@pytest.mark.parametrize(
    ("valid_button", "unknown_first"),
    [
        (whb04.Button.STOP, False),
        (whb04.Button.STOP, True),
        (whb04.Button.RESET, False),
        (whb04.Button.RESET, True),
    ],
)
def test_unknown_button_does_not_drop_valid_button_from_same_packet(valid_button, unknown_first):
    daemon = whb04.Daemon()
    pressed = []
    daemon.on_button_press = lambda _daemon, button: pressed.append(button)
    button1, button2 = (0xFF, valid_button.value) if unknown_first else (valid_button.value, 0xFF)
    packet = struct.pack(
        "BBBBBBbB",
        0x04,
        0,
        button1,
        button2,
        whb04.StepSize.LEAD.value,
        whb04.Axis.OFF.value,
        0,
        0,
    )

    daemon._process_input_packet(packet)

    assert pressed == [valid_button]
    assert daemon.pressed_buttons == {valid_button}
