"""Format tool definitions as toolbar tooltip text for the G-code viewer."""

from carveracontroller.addons.tool_visualization.tool_definition import ToolType
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
}


def _format_tool_type_label(tool_def):
    if tool_def.type_name:
        return tool_def.type_name
    msgid = TOOL_TYPE_MSGIDS.get(tool_def.tool_type)
    return tr._(msgid) if msgid else ""


def format_tool_tooltip(tool_def):
    """Return multi-line tooltip text for a parsed tool, or an empty string."""
    if tool_def is None:
        return ""

    title = f"T{tool_def.number}"
    type_label = _format_tool_type_label(tool_def)
    if type_label:
        title = f"{title} - {type_label}"

    lines = [title]

    dimensions = []
    if tool_def.diameter is not None:
        dimensions.append(tr._("D={value:g}").format(value=tool_def.diameter))
    if tool_def.shank_diameter is not None:
        dimensions.append(tr._("SD={value:g}").format(value=tool_def.shank_diameter))
    if tool_def.corner_radius is not None:
        dimensions.append(tr._("CR={value:g}").format(value=tool_def.corner_radius))
    if tool_def.taper_angle_deg is not None:
        dimensions.append(tr._("TAPER={value:g}°").format(value=tool_def.taper_angle_deg))
    if tool_def.length is not None:
        dimensions.append(tr._("L={value:g}").format(value=tool_def.length))
    if tool_def.flute_length is not None:
        dimensions.append(tr._("FL={value:g}").format(value=tool_def.flute_length))
    if tool_def.thread_depth is not None:
        dimensions.append(tr._("Thread depth={value:g}").format(value=tool_def.thread_depth))
    if tool_def.thread_pitch is not None:
        dimensions.append(tr._("Pitch={value:g}").format(value=tool_def.thread_pitch))
    if dimensions:
        lines.append(" ".join(dimensions))

    if tool_def.description:
        lines.append(tool_def.description)

    if tool_def.vendor:
        lines.append(" - {vendor}".format(vendor=tool_def.vendor))

    return "\n".join(lines)
