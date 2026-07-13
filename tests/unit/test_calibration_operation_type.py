"""Tests for calibration operation labels."""

from carveracontroller.addons.probing.operations.Calibration.CalibrationOperationType import (
    CalibrationOperationType,
)


def test_anchor2_operation_uses_anchor2_title():
    assert CalibrationOperationType.Anchor2.value.title == "Calibration - Anchor2"
