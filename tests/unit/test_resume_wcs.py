"""Tests for resume-at-line work coordinate system recovery."""

from carveracontroller.Controller import Controller


def test_g53_does_not_replace_active_work_coordinate_system():
    controller = Controller.__new__(Controller)
    controller._get_line_position_from_gcode_viewer = lambda _line: (None, None, None, None)
    lines = [
        "G55\n",
        "G53 G0 Z-2\n",
        "G1 X10 F100\n",
        "G1 X20\n",
    ]

    commands = controller.playStartLineCommand("job.nc", 4, preview=True, lines=lines)

    assert "buffer G55" in commands
    assert "buffer G53" not in commands
    assert "buffer G53 G0 Z-2" in commands
