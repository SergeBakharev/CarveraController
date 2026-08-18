"""Tests for OperationsBase.apply_direction and callers that invert axis values."""

import pytest

from carveracontroller.addons.probing.operations.Angle.AngleOperation import AngleOperation
from carveracontroller.addons.probing.operations.Angle.AngleParameterDefinitions import AngleParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase


class _DirectionOp(OperationsBase):
    def generate(self, config):
        return ""

    def get_missing_config(self, config):
        return None


@pytest.mark.parametrize("key", ["X", "Y", "Z", "E"])
@pytest.mark.parametrize("blank_value", ["", "   "])
def test_apply_direction_skips_blank_values(key, blank_value):
    op = _DirectionOp("test")
    config = {key: blank_value}

    op.apply_direction(key, config, True)

    assert config[key] == blank_value


@pytest.mark.parametrize("key", ["X", "Y", "Z", "E"])
def test_apply_direction_negates_numeric_string(key):
    op = _DirectionOp("test")
    config = {key: "2.5"}

    op.apply_direction(key, config, True)

    assert config[key] == "-2.5"


@pytest.mark.parametrize("key", ["X", "Y", "Z", "E"])
def test_apply_direction_leaves_value_when_not_opposite(key):
    op = _DirectionOp("test")
    config = {key: "2.5"}

    op.apply_direction(key, config, False)

    assert config[key] == "2.5"


def test_apply_direction_skips_missing_key():
    op = _DirectionOp("test")
    config = {"X": "2.5"}

    op.apply_direction("Y", config, True)

    assert config == {"X": "2.5"}


def test_apply_direction_skips_non_numeric_value():
    op = _DirectionOp("test")
    config = {"X": "abc"}

    op.apply_direction("X", config, True)

    assert config["X"] == "abc"


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_angle_generate_uses_negated_default_when_inverted_and_blank(blank_value):
    op = AngleOperation("Angle - X Above", True, False, True, "")
    inverted = AngleParameterDefinitions.ProbeDepth
    config = {
        AngleParameterDefinitions.XAxisDistance.code: "10",
        inverted.code: blank_value,
    }

    assert op.get_missing_config(config) is None
    gcode = op.generate(config)

    assert gcode.startswith("M465")
    assert f"{inverted.code}-2.0" in gcode


@pytest.mark.parametrize("blank_value", ["", "   "])
def test_angle_generate_uses_default_when_not_inverted_and_blank(blank_value):
    op = AngleOperation("Angle - X Below", True, False, False, "")
    depth = AngleParameterDefinitions.ProbeDepth
    config = {
        AngleParameterDefinitions.XAxisDistance.code: "10",
        depth.code: blank_value,
    }

    gcode = op.generate(config)

    assert gcode.startswith("M465")
    assert f"{depth.code}2" in gcode


def test_angle_generate_negates_inverted_value():
    op = AngleOperation("Angle - X Above", True, False, True, "")
    inverted = AngleParameterDefinitions.ProbeDepth
    config = {
        AngleParameterDefinitions.XAxisDistance.code: "10",
        inverted.code: "3",
    }

    gcode = op.generate(config)

    assert f"{inverted.code}-3.0" in gcode
