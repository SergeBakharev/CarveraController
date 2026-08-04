"""Helpers for working with Kivy widgets."""

from typing import Any

from kivy.clock import Clock


def bind_auto_select_to_text_input(widget: Any) -> None:
    def focus_handler(_input: Any, focused: bool) -> None:
        if focused:
            Clock.schedule_once(lambda _: widget.select_all(), 0.1)

    widget.bind(focus=focus_handler)
