"""Tests for resume-at-line feed-rate recovery."""

import pytest

from carveracontroller.Controller import Controller


@pytest.mark.parametrize(
    ("lines", "expected"),
    (
        (["G1 X0 F100\n", "F275\n", "G0 X1\n", "G1 X2\n"], 275.0),
        (["G1 X0 F100\n", "X10Y10G1F425\n", "G28\n", "G1 X2\n"], 425.0),
        (["G1 X0 F100\n", "G1 X1 ; F900\n", "G0 X2\n", "G1 X3\n"], 100.0),
        (["G1 X0 F100\n", "G1 X1 (F900)\n", "G0 X2\n", "G1 X3\n"], 100.0),
    ),
)
def test_recovers_feed_from_standalone_and_tightly_packed_words(lines, expected):
    controller = Controller.__new__(Controller)

    assert controller._find_last_feed_rate(lines, 4) == expected


def test_restores_feed_before_recovery_z_move():
    controller = Controller.__new__(Controller)
    controller._get_line_position_from_gcode_viewer = lambda _line: (1.0, 2.0, -3.0, None)
    lines = [
        "G55\n",
        "G1 X0 F100\n",
        "F275\n",
        "G1 X1\n",
        "G1 X2\n",
    ]

    commands = controller.playStartLineCommand("job.nc", 5, preview=True, lines=lines)

    feed_index = commands.index("buffer G1 F275")
    z_index = commands.index("buffer G1 Z-3.000")
    assert feed_index < z_index
