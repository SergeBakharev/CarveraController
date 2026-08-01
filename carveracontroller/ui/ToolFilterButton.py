"""Toolbar button for T1–T6 with a generated tool silhouette."""

from __future__ import annotations

from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.tool_visualization.icon_builder import (
    ICON_FLUTE_COLOR,
    ICON_FLUTE_DISABLED_COLOR,
    ICON_FLUTE_HIDDEN_COLOR,
    ICON_OUTLINE_COLOR,
    ICON_OUTLINE_DISABLED_COLOR,
    ICON_OUTLINE_HIDDEN_COLOR,
    ICON_OUTLINE_WIDTH_DP,
    ICON_SHANK_COLOR,
    ICON_SHANK_DISABLED_COLOR,
    ICON_SHANK_HIDDEN_COLOR,
)
from carveracontroller.addons.tool_visualization.icon_geometry import geometry_to_mesh
from carveracontroller.addons.tooltips.Tooltips import ToolTipButton


class ToolFilterButton(BoxLayout, ToolTipButton):
    """G-code viewer tool-filter button with a Mesh-drawn tool silhouette.

    Caption text lives in ``label_text`` (drawn by the child Label). The
    Button/Label base ``text`` stays empty so Kivy does not rasterize a second
    copy of the caption onto the root widget.
    """

    icon_size = NumericProperty(28)
    icon_pad_x = NumericProperty(6)
    label_text = StringProperty("")
    min_icon = StringProperty("")
    min_icon_size = NumericProperty(12)
    min_active = BooleanProperty(True)
    active = BooleanProperty(False)

    tool_icon_geometry = ObjectProperty(None, allownone=True)
    has_tool_icon = BooleanProperty(False)
    # Icon rect in widget coords: [x, y, w, h], fed from KV.
    icon_rect = ListProperty([0, 0, 0, 0])
    icon_flute_vertices = ListProperty([])
    icon_flute_indices = ListProperty([])
    icon_shank_vertices = ListProperty([])
    icon_shank_indices = ListProperty([])
    icon_outline_points = ListProperty([])
    # In dp; KV applies dp() so the stroke matches the tooltip rasterizer.
    icon_outline_width = NumericProperty(ICON_OUTLINE_WIDTH_DP)
    icon_flute_color = ListProperty(list(ICON_FLUTE_COLOR))
    icon_shank_color = ListProperty(list(ICON_SHANK_COLOR))
    icon_outline_color = ListProperty(list(ICON_OUTLINE_COLOR))

    def __init__(self, **kwargs):
        # Ensure Button/Label text stays empty even if callers pass text=.
        label_text = kwargs.pop("text", None)
        super().__init__(**kwargs)
        if label_text is not None:
            self.label_text = label_text
        self.text = ""
        self.fbind("disabled", self._sync_tool_icon_colors)
        self.fbind("min_active", self._sync_tool_icon_colors)
        self.fbind("tool_icon_geometry", self._rebuild_tool_icon_mesh)
        self.fbind("icon_rect", self._rebuild_tool_icon_mesh)

    def on_tool_icon_geometry(self, _instance, value):
        self.has_tool_icon = value is not None

    def _rebuild_tool_icon_mesh(self, *_args):
        geometry = self.tool_icon_geometry
        if geometry is None:
            self.icon_flute_vertices = []
            self.icon_flute_indices = []
            self.icon_shank_vertices = []
            self.icon_shank_indices = []
            self.icon_outline_points = []
            return
        x, y, width, height = self.icon_rect
        if width <= 0 or height <= 0:
            # Layout not ready yet; clear so we never keep a stale silhouette
            # after a geometry change, and wait for icon_rect to update.
            self.icon_flute_vertices = []
            self.icon_flute_indices = []
            self.icon_shank_vertices = []
            self.icon_shank_indices = []
            self.icon_outline_points = []
            return
        flute_v, flute_i, shank_v, shank_i, outline = geometry_to_mesh(geometry, x, y, width, height)
        self.icon_flute_vertices = flute_v
        self.icon_flute_indices = flute_i
        self.icon_shank_vertices = shank_v
        self.icon_shank_indices = shank_i
        self.icon_outline_points = outline

    def _sync_tool_icon_colors(self, *_args):
        # Disabled (unused slot): darker grey. Hidden (eye-off): mid grey.
        if self.disabled:
            self.icon_flute_color = list(ICON_FLUTE_DISABLED_COLOR)
            self.icon_shank_color = list(ICON_SHANK_DISABLED_COLOR)
            self.icon_outline_color = list(ICON_OUTLINE_DISABLED_COLOR)
        elif not self.min_active:
            self.icon_flute_color = list(ICON_FLUTE_HIDDEN_COLOR)
            self.icon_shank_color = list(ICON_SHANK_HIDDEN_COLOR)
            self.icon_outline_color = list(ICON_OUTLINE_HIDDEN_COLOR)
        else:
            self.icon_flute_color = list(ICON_FLUTE_COLOR)
            self.icon_shank_color = list(ICON_SHANK_COLOR)
            self.icon_outline_color = list(ICON_OUTLINE_COLOR)
