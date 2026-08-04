"""Section header label for directory dropdown menus."""

from kivy.factory import Factory
from kivy.uix.label import Label


class DropDownSplitter(Label):
    pass


if "DropDownSplitter" not in Factory.classes:
    Factory.register("DropDownSplitter", cls=DropDownSplitter)
