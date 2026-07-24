"""Tests for defensive pendant display updates."""

from types import SimpleNamespace

import pytest

from carveracontroller.addons.pendant import pendant as pendant_module
from carveracontroller.addons.pendant import whb04


@pytest.mark.parametrize(
    ("spindle_vars", "expected_speed"),
    [
        ({}, 0),
        ({"curspindle": None}, 0),
        ({"curspindle": "invalid"}, 0),
        ({"curspindle": -1}, 0),
        ({"curspindle": 70000}, 65535),
        ({"curspindle": "1234.5"}, 1234),
        ({"curspindle": float("nan")}, 0),
        ({"curspindle": float("inf")}, 0),
        ({"curspindle": float("-inf")}, 0),
        pytest.param({"curspindle": 10**10000}, 65535, id="huge-positive-integer"),
        pytest.param({"curspindle": -(10**10000)}, 0, id="huge-negative-integer"),
    ],
)
def test_whb04_display_sanitizes_spindle_speed(spindle_vars, expected_speed):
    pendant = pendant_module.WHB04.__new__(pendant_module.WHB04)
    pendant._cnc = SimpleNamespace(
        vars={
            "wx": 0.0,
            "wy": 0.0,
            "wz": 0.0,
            "wa": 0.0,
            "curfeed": 0.0,
            **spindle_vars,
        }
    )
    pendant._controller = SimpleNamespace(
        jog_mode=0,
        JOG_MODE_CONTINUOUS=1,
        JOG_MODE_STEP=0,
    )
    daemon = whb04.Daemon()
    daemon.set_display_spindle_speed(4321)

    pendant._handle_display_update(daemon)

    assert daemon._display_spindle_speed == expected_speed
