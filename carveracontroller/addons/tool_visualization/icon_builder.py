"""Map tool definitions to toolbar / tooltip icon paths for the G-code viewer."""

from carveracontroller.addons.tool_visualization.tool_definition import ToolType

TOOLS_ICON_DIR = "data/GcodeViewer/tools"
DEFAULT_ICON = f"{TOOLS_ICON_DIR}/pointed_mill.png"
DEFAULT_THUMB_ICON = f"{TOOLS_ICON_DIR}/pointed_mill_thumb.png"

# Full-body icons (used in tooltips)
TOOL_TYPE_ICONS = {
    ToolType.FLAT_END_MILL: f"{TOOLS_ICON_DIR}/flat_end_mill.png",
    ToolType.BALL_END_MILL: f"{TOOLS_ICON_DIR}/ball_end_mill.png",
    ToolType.BULL_NOSE_END_MILL: f"{TOOLS_ICON_DIR}/bull_nose_end_mill.png",
    ToolType.RADIUS_MILL: f"{TOOLS_ICON_DIR}/radius_mill.png",
    ToolType.CHAMFER_MILL: DEFAULT_ICON,
    ToolType.ENGRAVING: DEFAULT_ICON,
    ToolType.TAPERED_MILL: f"{TOOLS_ICON_DIR}/tapered_mill.png",
    ToolType.LOLLIPOP_MILL: f"{TOOLS_ICON_DIR}/lollipop_mill.png",
    ToolType.THREAD_MILL: f"{TOOLS_ICON_DIR}/thread_mill.png",
    ToolType.UNKNOWN: DEFAULT_ICON,
}

# Zoomed thumbnails (used on the T1–T6 buttons)
TOOL_TYPE_THUMB_ICONS = {
    ToolType.FLAT_END_MILL: f"{TOOLS_ICON_DIR}/flat_end_mill_thumb.png",
    ToolType.BALL_END_MILL: f"{TOOLS_ICON_DIR}/ball_end_mill_thumb.png",
    ToolType.BULL_NOSE_END_MILL: f"{TOOLS_ICON_DIR}/bull_nose_end_mill_thumb.png",
    ToolType.RADIUS_MILL: f"{TOOLS_ICON_DIR}/radius_mill_thumb.png",
    ToolType.CHAMFER_MILL: DEFAULT_THUMB_ICON,
    ToolType.ENGRAVING: DEFAULT_THUMB_ICON,
    ToolType.TAPERED_MILL: f"{TOOLS_ICON_DIR}/tapered_mill_thumb.png",
    ToolType.LOLLIPOP_MILL: f"{TOOLS_ICON_DIR}/lollipop_mill_thumb.png",
    ToolType.THREAD_MILL: f"{TOOLS_ICON_DIR}/thread_mill_thumb.png",
    ToolType.UNKNOWN: DEFAULT_THUMB_ICON,
}


def get_tool_icon_path(tool_def):
    """Return the toolbar thumb icon path for a tool definition."""
    if tool_def is None:
        return DEFAULT_THUMB_ICON
    return TOOL_TYPE_THUMB_ICONS.get(tool_def.tool_type, DEFAULT_THUMB_ICON)


def get_tool_tooltip_icon_path(tool_def):
    """Return the full-body tooltip icon path for a tool definition."""
    if tool_def is None:
        return DEFAULT_ICON
    return TOOL_TYPE_ICONS.get(tool_def.tool_type, DEFAULT_ICON)
