"""Format tool definitions as toolbar tooltip text for the G-code viewer."""

from carveracontroller.addons.tool_visualization.tool_definition import ToolType
from carveracontroller.CNC import escape_gcode_markup
from carveracontroller.translation import tr

TOOL_TYPE_MSGIDS = {
    ToolType.FLAT_END_MILL: "Flat End Mill",
    ToolType.BALL_END_MILL: "Ball End Mill",
    ToolType.BULL_NOSE_END_MILL: "Bull Nose End Mill",
    ToolType.RADIUS_MILL: "Radius Mill",
    ToolType.CHAMFER_MILL: "Chamfer Mill",
    ToolType.ENGRAVING: "Engraving",
    ToolType.TAPERED_MILL: "Tapered Mill",
    ToolType.LOLLIPOP_MILL: "Lollipop Mill",
    ToolType.THREAD_MILL: "Thread Mill",
    ToolType.DRILL: "Drill",
}

# Title size in px
_TITLE_SIZE = 17


def _format_tool_type_label(tool_def):
    # Prefer our canonical labels when the type is known
    msgid = TOOL_TYPE_MSGIDS.get(tool_def.tool_type)
    if msgid:
        return tr._(msgid)
    # Unknown types: keep the raw CAM name as-is
    return (tool_def.type_name or "").strip()


def _is_meaningful(value):
    """Return True when a numeric field should be shown (present and non-zero)."""
    return value is not None and value != 0


def _format_dimension_lines(tool_def):
    """Build one-label-per-line dimension rows, skipping redundant/noise fields."""
    lines = []

    if tool_def.diameter is not None:
        lines.append(tr._("Diameter: {value:g}").format(value=tool_def.diameter))

    # Shank is noise when it matches the cutting diameter (common inferred default).
    if _is_meaningful(tool_def.shank_diameter) and tool_def.shank_diameter != tool_def.diameter:
        lines.append(tr._("Shank: {value:g}").format(value=tool_def.shank_diameter))

    if _is_meaningful(tool_def.corner_radius):
        lines.append(tr._("Corner radius: {value:g}").format(value=tool_def.corner_radius))

    # Tip Ø is noise when it matches the cutting diameter (flat/ball/drill exports).
    if _is_meaningful(tool_def.tip_diameter) and tool_def.tip_diameter != tool_def.diameter:
        lines.append(tr._("Tip diameter: {value:g}").format(value=tool_def.tip_diameter))

    if _is_meaningful(tool_def.taper_angle_deg):
        lines.append(tr._("Taper: {value:g}°").format(value=tool_def.taper_angle_deg))

    if _is_meaningful(tool_def.length):
        lines.append(tr._("Length: {value:g}").format(value=tool_def.length))

    if _is_meaningful(tool_def.flute_length):
        lines.append(tr._("Flute length: {value:g}").format(value=tool_def.flute_length))

    if _is_meaningful(tool_def.shoulder_length):
        lines.append(tr._("Shoulder: {value:g}").format(value=tool_def.shoulder_length))

    if _is_meaningful(tool_def.thread_depth):
        lines.append(tr._("Thread depth: {value:g}").format(value=tool_def.thread_depth))

    if _is_meaningful(tool_def.thread_pitch):
        lines.append(tr._("Pitch: {value:g}").format(value=tool_def.thread_pitch))

    return lines


def _format_catalog_line(tool_def):
    return tool_def.vendor or ""


def format_tool_tooltip(tool_def, *, markup=True):
    """Return multi-line tooltip text for a parsed tool, or an empty string.

    When *markup* is True (default), the string includes Kivy Label markup for
    hierarchy (larger title). Pass markup=False for plain text consumers such
    as the tool-change confirm popup.
    """
    if tool_def is None:
        return ""

    title = f"T{tool_def.number}"
    type_label = _format_tool_type_label(tool_def)
    if type_label:
        title = f"{title} · {type_label}"

    description = tool_def.description or ""
    catalog = _format_catalog_line(tool_def)

    if markup:
        title = f"[size={_TITLE_SIZE}]{escape_gcode_markup(title)}[/size]"
        if description:
            description = escape_gcode_markup(description)
        if catalog:
            catalog = escape_gcode_markup(catalog)

    identity = [title]
    if description:
        identity.append(description)
    if catalog:
        identity.append(catalog)

    sections = ["\n".join(identity)]

    dimension_lines = _format_dimension_lines(tool_def)
    if dimension_lines:
        if markup:
            dimension_lines = [escape_gcode_markup(line) for line in dimension_lines]
        sections.append("\n".join(dimension_lines))

    return "\n\n".join(sections)
