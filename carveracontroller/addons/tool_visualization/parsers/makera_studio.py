"""Parser for tool tables written by Makera Studio.

Makera Studio writes a `;@MKR|...` metadata block at the top of the G-code
file. Each tool is one line:

;@MKR|TOOL|number=<int>|id=<string>|name=<string>|type=<string>|handlediameter=<float>|sticklength=<float>|shoulderlength=<float>|flutelength=<float>|diameter=<float>|tipdiameter=<float>|cornerradius=<float>|angle=<float>|halfAngle=<float>
"""

import logging

from carveracontroller.addons.tool_visualization.parsers.base import ToolTableParser
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType, resolve_tool_type

logger = logging.getLogger(__name__)

# Tool type names as exported by Makera Studio
# TODO Update with confirmed IDs from Makera Studio.
TOOL_TYPE_NAME_MAP = {
    "flat end": ToolType.FLAT_END_MILL,
    "ball end": ToolType.BALL_END_MILL,
    "bull nose": ToolType.BULL_NOSE_END_MILL,
    "bullnose": ToolType.BULL_NOSE_END_MILL,
    "radius": ToolType.RADIUS_MILL,
    "radius mill": ToolType.RADIUS_MILL,
    "engraving": ToolType.ENGRAVING,
    "chamfer": ToolType.CHAMFER_MILL,
    "chamfer mill": ToolType.CHAMFER_MILL,
    "tapered": ToolType.TAPERED_MILL,
    "tapered mill": ToolType.TAPERED_MILL,
    "lollipop": ToolType.LOLLIPOP_MILL,
    "lollipop mill": ToolType.LOLLIPOP_MILL,
    "thread": ToolType.THREAD_MILL,
    "thread mill": ToolType.THREAD_MILL,
}

_MKR_PREFIX = ";@MKR|"
_TOOL_TAG = "TOOL"


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _positive_or_none(value):
    if value is None or value <= 0:
        return None
    return value


def _parse_mkr_fields(line):
    """Return (tag, fields_dict) for a `;@MKR|TAG|k=v|...` line, or None."""
    stripped = line.strip()
    if not stripped.startswith(_MKR_PREFIX):
        return None

    parts = stripped[len(_MKR_PREFIX) :].split("|")
    if not parts:
        return None

    tag = parts[0]
    fields = {}
    for part in parts[1:]:
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            continue
        fields[key] = value
    return tag, fields


def _taper_angle_from_fields(fields):
    angle = _to_float(fields.get("angle"))
    if angle is not None and angle > 0:
        return angle
    half_angle = _to_float(fields.get("halfAngle"))
    if half_angle is not None and half_angle > 0:
        return 2.0 * half_angle
    return None


def _stick_length_from_fields(fields):
    """Overall stick-out: prefer sticklength, fall back to shoulderlength."""
    stick = _positive_or_none(_to_float(fields.get("sticklength")))
    if stick is not None:
        return stick
    return _positive_or_none(_to_float(fields.get("shoulderlength")))


class MakeraStudioParser(ToolTableParser):
    name = "makera_studio"

    def parse(self, lines):
        tool_table = {}
        for raw_line in self.iter_header_lines(lines):
            parsed = _parse_mkr_fields(raw_line)
            if parsed is None:
                continue

            tag, fields = parsed
            if tag != _TOOL_TAG:
                continue

            number = _to_int(fields.get("number"))
            if number is None:
                continue
            if number in tool_table:
                logger.debug(f"Ignoring duplicate Makera Studio tool comment for T{number}: {raw_line.strip()}")
                continue

            tool_def = self._build_tool_definition(number, fields)
            tool_table[number] = tool_def

            if tool_def.tool_type is ToolType.UNKNOWN:
                logger.warning(
                    f"Detected T{number} ({tool_def.description!r}, D={tool_def.diameter}) "
                    f"with unrecognised tool type {tool_def.type_name!r}; defaulting to a basic pointed mesh"
                )
            else:
                dims = f"D={tool_def.diameter}, CR={tool_def.corner_radius}"
                if tool_def.taper_angle_deg is not None:
                    dims += f", TAPER={tool_def.taper_angle_deg}"
                logger.info(f"Detected T{number}: {tool_def.tool_type.value} ({dims}) - {tool_def.description!r}")

        return tool_table

    @staticmethod
    def _build_tool_definition(number, fields):
        type_name = fields.get("type", "") or ""
        handle_diameter = _positive_or_none(_to_float(fields.get("handlediameter")))

        return ToolDefinition(
            number=number,
            tool_type=resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP),
            diameter=_to_float(fields.get("diameter")),
            shank_diameter=handle_diameter,
            tip_diameter=_to_float(fields.get("tipdiameter")),
            corner_radius=_to_float(fields.get("cornerradius")),
            taper_angle_deg=_taper_angle_from_fields(fields),
            length=_stick_length_from_fields(fields),
            flute_length=_positive_or_none(_to_float(fields.get("flutelength"))),
            shoulder_length=_positive_or_none(_to_float(fields.get("shoulderlength"))),
            description=fields.get("name", "") or "",
            product_id=fields.get("id", "") or "",
            type_name=type_name,
        )
