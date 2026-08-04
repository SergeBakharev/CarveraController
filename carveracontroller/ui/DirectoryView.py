"""Directory shortcut row for local/remote file browser dropdowns."""

from kivy.factory import Factory
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton


class DirectoryView(BoxLayout, ToolTipButton):
    selected = BooleanProperty(False)
    data_text = StringProperty("")
    data_icon = StringProperty("data/folder-32.png")
    full_path = StringProperty("")


if "DirectoryView" not in Factory.classes:
    Factory.register("DirectoryView", cls=DirectoryView)
