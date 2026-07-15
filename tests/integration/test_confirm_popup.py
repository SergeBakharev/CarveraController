"""Regression tests for reusable confirmation-dialog state."""

from tests.integration.conftest import pump_frames


def assert_next_standard_confirmation_uses_default_layout(root):
    root.confirm_popup.dismiss()
    pump_frames(2)
    root.open_setting_restore_confirm_popup()
    pump_frames(2)

    popup = root.confirm_popup
    assert tuple(popup.size_hint) == (0.5, 0.4)
    assert popup.pos_hint == {"right": 0.75, "top": 0.7}
    assert popup.lb_title.size_hint_y == 0.4

    popup.dismiss()
    pump_frames(2)


def test_laser_confirmation_layout_does_not_leak_into_next_dialog(kivy_app):
    root = kivy_app.root
    popup = root.confirm_popup

    root.enable_laser_mode_confirm_popup()
    pump_frames(2)
    assert tuple(popup.size_hint) == (0.6, 0.7)
    assert popup.pos_hint == {"center_x": 0.5, "center_y": 0.5}
    assert popup.lb_title.size_hint_y is None

    assert_next_standard_confirmation_uses_default_layout(root)


def test_resume_confirmation_layout_does_not_leak_into_next_dialog(kivy_app, monkeypatch):
    app = kivy_app
    root = app.root
    popup = root.confirm_popup
    original_state = {
        "selected_remote_filename": app.selected_remote_filename,
        "selected_local_filename": app.selected_local_filename,
        "lines": root.lines,
        "_last_loaded_file_key": root._last_loaded_file_key,
        "loading_file": getattr(root, "loading_file", False),
        "selected_file_line_count": root.selected_file_line_count,
        "file_has_ocodes": root.file_has_ocodes,
    }

    try:
        app.selected_remote_filename = "job.nc"
        app.selected_local_filename = ""
        root.lines = ["G0 X0"]
        root._last_loaded_file_key = "job.nc"
        root.loading_file = False
        root.selected_file_line_count = 1
        root.file_has_ocodes = False
        monkeypatch.setattr(root.controller, "playStartLineCommand", lambda *args, **kwargs: ["G0 X0"])

        root.open_resume_playback_confirm_popup("job.nc", 1)
        pump_frames(2)
        assert tuple(popup.size_hint) == (0.8, 0.8)
        assert popup.pos_hint == {"center_x": 0.5, "center_y": 0.5}

        assert_next_standard_confirmation_uses_default_layout(root)
    finally:
        if popup.parent:
            popup.dismiss()
            pump_frames(2)
        for name, value in original_state.items():
            target = app if name.startswith("selected_") and name.endswith("_filename") else root
            setattr(target, name, value)
