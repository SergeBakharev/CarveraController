"""Parser for tool tables written by the Fusion 360 Makera post processor.

The post processor's `dumpToolInformation()` CPS function writes one comment
line per tool, on its own line, with the following layout:

T<number>  <description>  <vendor>  <productId>  D=<diameter>
  [CR=<cornerRadius>] [SD=<shaftDiameter>] [TD=<tipDiameter>] [FL=<fluteLength>]
  [SL=<shoulderLength>] [BL=<bodyLength>] [TP=<threadPitch>] [TAPER=<angle>deg]
  [- ZMIN=<zmin>] - <toolTypeName>
"""

import logging
import re

from carveracontroller.addons.tool_visualization.parsers.base import ToolTableParser
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType, resolve_tool_type

logger = logging.getLogger(__name__)

# Tool type names as exported by the getToolTypeName() function of Fusion.
TOOL_TYPE_NAME_MAP = {
    "flat end mill": ToolType.FLAT_END_MILL,
    "ball end mill": ToolType.BALL_END_MILL,
    "bull nose end mill": ToolType.BULL_NOSE_END_MILL,
    "radius mill": ToolType.RADIUS_MILL,
    "chamfer mill": ToolType.CHAMFER_MILL,
    "tapered mill": ToolType.TAPERED_MILL,
    "lollipop mill": ToolType.LOLLIPOP_MILL,
    "thread mill": ToolType.THREAD_MILL,
}

_NUMBER = r"[-+]?\d+\.?\d*"

TOOL_LINE_RE = re.compile(
    r"^T(?P<number>\d+)\s+(?P<middle>.*?)\s+D=(?P<diameter>" + _NUMBER + r")"
    r"(?:\s+CR=(?P<corner_radius>" + _NUMBER + r"))?"
    r"(?:\s+SD=(?P<shaft_diameter>" + _NUMBER + r"))?"
    r"(?:\s+TD=(?P<tip_diameter>" + _NUMBER + r"))?"
    r"(?:\s+FL=(?P<flute_length>" + _NUMBER + r"))?"
    r"(?:\s+SL=(?P<shoulder_length>" + _NUMBER + r"))?"
    r"(?:\s+BL=(?P<body_length>" + _NUMBER + r"))?"
    r"(?:\s+TP=(?P<thread_pitch>" + _NUMBER + r"))?"
    r"(?:\s+TAPER=(?P<taper>" + _NUMBER + r")deg)?"
    r"(?:\s*-\s*ZMIN=" + _NUMBER + r")?"
    r"\s*-\s*(?P<type_name>.+?)\s*$",
    re.IGNORECASE,
)

_FIELD_SPLIT_RE = re.compile(r"\s{2,}")


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _positive_or_none(value):
    if value is None or value <= 0:
        return None
    return value


def _infer_shank_diameter(tool_type, diameter, corner_radius=None):
    """Infer shank diameter from Fusion cutting geometry.

    Returns None when diameter is missing or the type's shaft cannot be derived
    from cutting geometry alone (tapered tip/lollipop ball).
    """
    if diameter is None or diameter <= 0:
        return None
    if tool_type is ToolType.RADIUS_MILL:
        return diameter + 2.0 * (corner_radius or 0.0)
    if tool_type in (ToolType.TAPERED_MILL, ToolType.LOLLIPOP_MILL):
        return None
    return diameter


def _extract_full_line_comment(line):
    """Return the text of a comment if the whole (stripped) line is one, else None."""
    if len(line) >= 2 and line[0] == "(" and line[-1] == ")":
        return line[1:-1]
    if line.startswith(";"):
        return line[1:]
    return None


class Fusion360MakeraParser(ToolTableParser):
    name = "fusion360_makera"

    def parse(self, lines):
        tool_table = {}
        for raw_line in self.iter_header_lines(lines):
            line = raw_line.strip()
            if not line:
                continue

            comment_text = _extract_full_line_comment(line)
            if comment_text is None:
                continue

            match = TOOL_LINE_RE.match(comment_text.strip())
            if not match:
                continue

            number = int(match.group("number"))
            if number in tool_table:
                # Only the first occurrence of a given tool should be used.
                logger.debug(f"Ignoring duplicate tool table comment for T{number}: {line}")
                continue

            tool_def = self._build_tool_definition(number, match)
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
    def _build_tool_definition(number, match):
        middle = match.group("middle").strip()
        fields = [field for field in _FIELD_SPLIT_RE.split(middle) if field]
        description = fields[0] if len(fields) > 0 else ""
        vendor = fields[1] if len(fields) > 1 else ""
        product_id = fields[2] if len(fields) > 2 else ""

        type_name = match.group("type_name").strip()
        tool_type = resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP)
        diameter = _to_float(match.group("diameter"))
        corner_radius = _to_float(match.group("corner_radius"))
        shaft_diameter = _positive_or_none(_to_float(match.group("shaft_diameter")))
        tip_diameter = _to_float(match.group("tip_diameter"))
        flute_length = _positive_or_none(_to_float(match.group("flute_length")))
        shoulder_length = _positive_or_none(_to_float(match.group("shoulder_length")))
        body_length = _positive_or_none(_to_float(match.group("body_length")))
        thread_pitch = _positive_or_none(_to_float(match.group("thread_pitch")))

        return ToolDefinition(
            number=number,
            tool_type=tool_type,
            diameter=diameter,
            shank_diameter=shaft_diameter
            if shaft_diameter is not None
            else _infer_shank_diameter(tool_type, diameter, corner_radius),
            tip_diameter=tip_diameter,
            corner_radius=corner_radius,
            taper_angle_deg=_to_float(match.group("taper")),
            length=body_length if body_length is not None else shoulder_length,
            flute_length=flute_length,
            shoulder_length=shoulder_length,
            thread_pitch=thread_pitch,
            description=description,
            vendor=vendor,
            product_id=product_id,
            type_name=type_name,
        )
