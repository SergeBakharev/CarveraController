"""Tests for firmware version parsing in Utils.digitize_v."""

from carveracontroller.Utils import digitize_v


def test_digitize_v_handles_community_rc_versions():
    assert digitize_v("2.2.0") == digitize_v("2.2.0-RC1")
    assert digitize_v("2.2.0") == digitize_v("2.2.0c-RC1")
    assert digitize_v("2.2.0-RC1") >= digitize_v("2.2.0")
    assert digitize_v("2.1.0-RC1") < digitize_v("2.2.0")


def test_digitize_v_empty_version():
    assert digitize_v("") == 0
