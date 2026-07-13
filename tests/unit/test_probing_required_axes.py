"""Tests for conditionally required probing axes."""

import pytest

from carveracontroller.addons.probing.operations.Angle.AngleOperation import AngleOperation
from carveracontroller.addons.probing.operations.Angle.AngleParameterDefinitions import AngleParameterDefinitions
from carveracontroller.addons.probing.operations.Bore.BoreOperation import BoreOperation
from carveracontroller.addons.probing.operations.Bore.BoreParameterDefinitions import BoreParameterDefinitions
from carveracontroller.addons.probing.operations.Boss.BossOperation import BossOperation
from carveracontroller.addons.probing.operations.Boss.BossParameterDefinitions import BossParameterDefinitions
from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipOperation import (
    ProbeTipOperationAnchor,
    ProbeTipOperationBore,
    ProbeTipOperationBoss,
)
from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipParameterDefinitions import (
    ProbeTipParameterDefinitions,
)

OPERATION_TYPES = (
    (BoreOperation, ("",), BoreParameterDefinitions),
    (BossOperation, ("",), BossParameterDefinitions),
    (AngleOperation, (False, ""), AngleParameterDefinitions),
    (ProbeTipOperationBore, (False, ""), ProbeTipParameterDefinitions),
    (ProbeTipOperationBoss, (False, ""), ProbeTipParameterDefinitions),
    (ProbeTipOperationAnchor, (False, ""), ProbeTipParameterDefinitions),
)


@pytest.mark.parametrize("blank_value", ["", "   "])
@pytest.mark.parametrize(("operation_type", "extra_args", "definitions"), OPERATION_TYPES)
@pytest.mark.parametrize(
    ("requires_x", "requires_y", "axis_name"),
    [
        (True, False, "XAxisDistance"),
        (False, True, "YAxisDistance"),
    ],
)
def test_conditionally_required_axis_rejects_blank_value(
    operation_type,
    extra_args,
    definitions,
    requires_x,
    requires_y,
    axis_name,
    blank_value,
):
    operation = operation_type("Test", requires_x, requires_y, *extra_args)
    definition = getattr(definitions, axis_name)

    missing = operation.get_missing_config({definition.code: blank_value})

    assert missing is definition


@pytest.mark.parametrize("configured_value", ["0", "12.5"])
@pytest.mark.parametrize(("operation_type", "extra_args", "definitions"), OPERATION_TYPES)
@pytest.mark.parametrize(
    ("requires_x", "requires_y", "axis_name"),
    [
        (True, False, "XAxisDistance"),
        (False, True, "YAxisDistance"),
    ],
)
def test_conditionally_required_axis_accepts_numeric_string(
    operation_type,
    extra_args,
    definitions,
    requires_x,
    requires_y,
    axis_name,
    configured_value,
):
    operation = operation_type("Test", requires_x, requires_y, *extra_args)
    definition = getattr(definitions, axis_name)

    missing = operation.get_missing_config({definition.code: configured_value})

    assert missing is not definition
