from kivy.properties import StringProperty
from kivy.uix.gridlayout import GridLayout

from ...addons.tooltips.Tooltips import ToolTipButton


class ProbeButton(ToolTipButton):
    def __init__(self, image="", halign="center", valign="middle", **kwargs):
        super().__init__(**kwargs)
        self.halign = halign
        self.valign = valign

    def on_size(self, *args):
        pass
        # at some point add code to respect halign and valign in img
