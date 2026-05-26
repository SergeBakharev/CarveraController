"""Popups for setting axis offsets and tool number."""

from functools import partial
from typing import Any

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import ObjectProperty, StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.translation import tr
from carveracontroller.ui import widget_helpers


def _show_error(message: str) -> None:
    """Display a validation error via the root widget's message popup."""
    app = App.get_running_app()
    Clock.schedule_once(partial(app.root.show_message_popup, message, False), 0)


def _validate_float(text: str, label: str) -> tuple[bool, str]:
    """Validate that `text` is a non-empty float; return (ok, error_message)."""
    stripped = text.strip()
    if not stripped:
        return False, tr._(f"Please enter a value for {label}.")
    try:
        float(stripped)
    except ValueError:
        return False, tr._(f"Please enter a valid number for {label}.")
    return True, ""


class SingleFloatPopup(ModalView):
    title = StringProperty("")
    hint = StringProperty("")
    label = StringProperty("")
    machine_op = ObjectProperty(None)

    def __init__(self, coord_popup: Any, **kwargs: Any) -> None:
        self.coord_popup = coord_popup
        super().__init__(**kwargs)

    def on_ok_pressed(self) -> None:
        is_valid, error = _validate_float(self.ids.txt_offset.text, self.label)
        if is_valid:
            app = App.get_running_app()
            self.machine_op(app.root.controller, float(self.ids.txt_offset.text))
            self.dismiss()
        else:
            _show_error(error)


class ToolPopup(ModalView):
    title = StringProperty("")
    hint = StringProperty("")
    machine_op = ObjectProperty(None)

    def __init__(self, coord_popup: Any, **kwargs: Any) -> None:
        self.coord_popup = coord_popup
        super().__init__(**kwargs)

    def on_open(self) -> None:
        super().on_open()
        widget_helpers.bind_auto_select_to_text_input(self.txt_offset)

    def on_ok_pressed(self) -> None:
        app = App.get_running_app()
        self.machine_op(app.root.controller, self.ids.txt_offset.text)
        self.dismiss()


class SetXPopup(SingleFloatPopup):
    pass


class SetYPopup(SingleFloatPopup):
    pass


class SetZPopup(SingleFloatPopup):
    pass


class SetAPopup(SingleFloatPopup):
    pass


class MoveAPopup(SingleFloatPopup):
    pass


class SetToolPopup(ToolPopup):
    pass


class ChangeToolPopup(ToolPopup):
    pass
