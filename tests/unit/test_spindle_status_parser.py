"""Tests for |S: spindle status parsing in Controller.parseBracketAngle."""

import pytest

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller


@pytest.fixture(autouse=True)
def reset_spindle_status():
    CNC.vars["vacuummode"] = 0
    CNC.vars["extoutmode"] = 0
    CNC.vars["spindletemp"] = 0.0


def _parse_status_line(line):
    controller = Controller(CNC(), lambda _line: None, False)
    controller.parseBracketAngle(line)


def test_spindle_status_with_spindle_temp_and_extout():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|S:10000.0,10000.0,100.0,0,35.2,42.1,0,0,1>")
    assert CNC.vars["vacuummode"] == 0
    assert CNC.vars["spindletemp"] == 35.2
    assert CNC.vars["extoutmode"] == 1


def test_spindle_status_without_spindle_temp_and_extout():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|S:10000.0,10000.0,100.0,0,42.1,0,0,1>")
    assert CNC.vars["vacuummode"] == 0
    assert CNC.vars["extoutmode"] == 1


def test_spindle_status_legacy_format():
    _parse_status_line("<Idle|MPos:0,0,0|WPos:0,0,0|S:10000.0,10000.0,100.0,1,25.0>")
    assert CNC.vars["vacuummode"] == 1
    assert CNC.vars["spindletemp"] == 25.0
    assert CNC.vars["extoutmode"] == 0
