"""Tests for resume-at-line spindle-speed recovery."""

import pytest

from carveracontroller.Controller import Controller


@pytest.mark.parametrize(
    ("lines", "start_line", "expected"),
    (
        (["M03 S12000\n", "G1 X1\n"], 2, 12000.0),
        (["S8000M03\n", "G1 X1\n"], 2, 8000.0),
        (["M03 S6000\n", "M03\n", "G1 X1\n"], 3, 6000.0),
        (["M3 S7000\n", "M030 S9999\n", "G1 X1\n"], 3, 7000.0),
        (["M03 S5000\n", "G1 X1 (M03 S9999)\n", "G1 X2\n"], 3, 5000.0),
    ),
)
def test_recovers_speed_from_zero_padded_m03(lines, start_line, expected):
    controller = Controller.__new__(Controller)

    assert controller._find_m3_spindle_speed(lines, start_line) == expected


def test_resume_preview_includes_m03_speed():
    controller = Controller.__new__(Controller)
    controller._get_line_position_from_gcode_viewer = lambda _line: (None, None, None, None)
    lines = [
        "M03 S12000\n",
        "G1 X1 F100\n",
        "G1 X2\n",
    ]

    commands = controller.playStartLineCommand("job.nc", 3, preview=True, lines=lines)

    assert "buffer M3 S12000" in commands
    assert "buffer M3" not in commands
