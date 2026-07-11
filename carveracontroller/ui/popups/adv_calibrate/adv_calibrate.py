"""Advanced tool calibration popup (M491 with optional parameters)."""

from functools import partial
from typing import Any

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.translation import tr
from carveracontroller.ui import widget_helpers

SETTINGS_FILENAME = "adv-calibrate-settings.json"


def load_adv_calibrate_settings() -> dict[str, str]:
    return ConfigUtils.load_config(SETTINGS_FILENAME)


def save_adv_calibrate_settings(repeat: str, x_offset: str, y_offset: str) -> None:
    ConfigUtils.save_config(
        {
            "repeat": repeat.strip(),
            "x_offset": x_offset.strip(),
            "y_offset": y_offset.strip(),
        },
        SETTINGS_FILENAME,
    )


def _show_error(message: str) -> None:
    app = App.get_running_app()
    Clock.schedule_once(partial(app.root.show_message_popup, message, False), 0)


def _parse_optional_float(text: str, default: float) -> float:
    stripped = text.strip().replace(",", ".")
    if not stripped:
        return default
    return float(stripped)


def _parse_optional_int(text: str, default: int) -> int:
    stripped = text.strip().replace(",", ".")
    if not stripped:
        return default
    return int(float(stripped))


class AdvCalibratePopup(ModalView):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._auto_select_bound = False

    def on_open(self) -> None:
        super().on_open()
        ids = self.ids
        settings = load_adv_calibrate_settings()
        ids.txt_repeat.text = settings.get("repeat", "")
        ids.txt_x_offset.text = settings.get("x_offset", "")
        ids.txt_y_offset.text = settings.get("y_offset", "")
        if not self._auto_select_bound:
            widget_helpers.bind_auto_select_to_text_input(ids.txt_repeat)
            widget_helpers.bind_auto_select_to_text_input(ids.txt_x_offset)
            widget_helpers.bind_auto_select_to_text_input(ids.txt_y_offset)
            self._auto_select_bound = True

    def _persist_settings(self) -> None:
        ids = self.ids
        save_adv_calibrate_settings(ids.txt_repeat.text, ids.txt_x_offset.text, ids.txt_y_offset.text)

    def dismiss(self, *args: Any, **kwargs: Any) -> None:
        self._persist_settings()
        super().dismiss(*args, **kwargs)

    def on_run_pressed(self) -> None:
        ids = self.ids
        try:
            repeat_count = _parse_optional_int(ids.txt_repeat.text, 1)
            x_offset = _parse_optional_float(ids.txt_x_offset.text, 0.0)
            y_offset = _parse_optional_float(ids.txt_y_offset.text, 0.0)
        except ValueError:
            _show_error(tr._("Please enter valid numbers for all fields."))
            return

        if repeat_count < 1:
            _show_error(tr._("Number of measurement repeats must be at least 1."))
            return

        app = App.get_running_app()
        app.root.controller.calibrate_tool_advanced_command(
            repeat_count=repeat_count,
            x_offset=x_offset,
            y_offset=y_offset,
        )
        self.dismiss()
