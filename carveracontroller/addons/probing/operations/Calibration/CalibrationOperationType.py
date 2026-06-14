from enum import Enum

from carveracontroller.addons.probing.operations.Calibration.CalibrationOperation import (
    CalibrationOperationAnchor1,
    CalibrationOperationAnchor2,
    CalibrationOperationFourthY,
    CalibrationOperationFourthZ,
)


class CalibrationOperationType(Enum):
    FourthY = CalibrationOperationFourthY("Calibration - FourthY", False, False, False, "")
    FourthZ = CalibrationOperationFourthZ("Calibration - FourthZ", True, False, False, "")
    Anchor1 = CalibrationOperationAnchor1("Calibration - Anchor1", False, False, False, "")
    Anchor2 = CalibrationOperationAnchor2("Calibration - Anchor1", False, False, False, "")
