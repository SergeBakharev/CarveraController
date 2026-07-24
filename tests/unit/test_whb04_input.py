"""Tests for defensive WHB04 input packet handling."""

import struct

import pytest

from carveracontroller.addons.pendant import whb04


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
