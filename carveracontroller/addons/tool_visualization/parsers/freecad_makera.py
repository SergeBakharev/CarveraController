"""Parser for tool tables written by the FreeCAD Makera post processor.

The post processor writes a comment block at the top of the G-code file:

(@FC|TOOL|number=<int>|name=<string>|vendor=<string>|id=<string>|type=<ShapeType>|diameter=<float>|shankdiameter=<float>|tipdiameter=<float>|cornerradius=<float>|flutelength=<float>|shoulderlength=<float>|length=<float>|pitch=<float>|cuttingedgeangle=<float>|tipangle=<float>|taperangle=<float>)

`type` is FreeCAD's native ShapeType (Endmill, Ballend, Drill, VBit, ...).

Angle fields are FreeCAD's raw values in degrees:
- tipangle: included drill tip angle
- taperangle: included taper angle (Tapered Ball Nose)
- cuttingedgeangle: included V/chamfer cutting-edge angle

The parser converts those included angles to per-side degrees for ToolDefinition.
"""

import logging

from carveracontroller.addons.tool_visualization.parsers.base import ToolTableParser
from carveracontroller.addons.tool_visualization.tool_definition import (
    ToolDefinition,
    ToolType,
    resolve_tool_type,
)

logger = logging.getLogger(__name__)

# FreeCAD ShapeType / shape filename stems as written in `type=`.
TOOL_TYPE_NAME_MAP = {
    "endmill": ToolType.FLAT_END_MILL,
    "ballend": ToolType.BALL_END_MILL,
    "bullnose": ToolType.BULL_NOSE_END_MILL,
    "chamfer": ToolType.CHAMFER_MILL,
    "vbit": ToolType.CHAMFER_MILL,
    "v-bit": ToolType.CHAMFER_MILL,
    "drill": ToolType.DRILL,
    "threadmill": ToolType.THREAD_MILL,
    "thread-mill": ToolType.THREAD_MILL,
    "thread mill": ToolType.THREAD_MILL,
    "taperedballnose": ToolType.TAPERED_MILL,
    "tapered ball nose": ToolType.TAPERED_MILL,
    "radius": ToolType.RADIUS_MILL,
    "radius mill": ToolType.RADIUS_MILL,
}

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


def _extract_fc_payload(line):
    """Return the `@FC|...` payload from a FreeCAD tool-table comment, else None."""
    stripped = line.strip()
    if stripped.startswith("(@FC|") and stripped.endswith(")"):
        return stripped[1:-1]
    if stripped.startswith(";@FC|"):
        return stripped[1:]
    return None


def _parse_fc_fields(line):
    """Return (tag, fields_dict) for an `@FC|TAG|k=v|...` payload, or None."""
    payload = _extract_fc_payload(line)
    if payload is None or not payload.startswith("@FC|"):
        return None

    parts = payload[len("@FC|") :].split("|")
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


def _included_to_per_side(angle_deg):
    """Convert an included tip/taper angle to per-side degrees."""
    if angle_deg is None or angle_deg <= 0:
        return None
    # Guard against bad FreeCAD library data (e.g. drills with angle > 180).
    if angle_deg > 180:
        return None
    return angle_deg / 2.0


def _taper_angle_from_fields(fields, tool_type):
    """Return per-side taper in degrees from FreeCAD angle fields."""
    tip_angle = _included_to_per_side(_to_float(fields.get("tipangle")))
    if tip_angle is not None and tool_type is ToolType.DRILL:
        return tip_angle

    taper_angle = _included_to_per_side(_to_float(fields.get("taperangle")))
    if taper_angle is not None:
        return taper_angle

    cutting_edge_angle = _included_to_per_side(_to_float(fields.get("cuttingedgeangle")))
    if cutting_edge_angle is None:
        return None

    if tool_type in (
        ToolType.CHAMFER_MILL,
        ToolType.ENGRAVING,
        ToolType.DRILL,
        ToolType.TAPERED_MILL,
    ):
        return cutting_edge_angle
    return None


class FreeCADMakeraParser(ToolTableParser):
    name = "freecad_makera"

    def parse(self, lines):
        tool_table = {}
        saw_fc_marker = False

        for raw_line in self.iter_header_lines(lines):
            parsed = _parse_fc_fields(raw_line)
            if parsed is None:
                # Keep scanning header comments; Fusion-style lines must not
                # make us bail before we see any @FC markers.
                continue

            saw_fc_marker = True
            tag, fields = parsed
            if tag != _TOOL_TAG:
                continue

            number = _to_int(fields.get("number"))
            if number is None:
                continue
            if number in tool_table:
                logger.debug(f"Ignoring duplicate FreeCAD tool comment for T{number}: {raw_line.strip()}")
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

        if not saw_fc_marker:
            return {}
        return tool_table

    @staticmethod
    def _build_tool_definition(number, fields):
        type_name = fields.get("type", "") or ""
        tool_type = resolve_tool_type(type_name, TOOL_TYPE_NAME_MAP)
        diameter = _to_float(fields.get("diameter"))
        tip_diameter = _to_float(fields.get("tipdiameter"))
        corner_radius = _to_float(fields.get("cornerradius"))
        shank_diameter = _positive_or_none(_to_float(fields.get("shankdiameter")))

        # Tapered ball nose is a ball tip (CR = D/2) with a conical taper above.
        if tool_type is ToolType.TAPERED_MILL:
            if diameter is not None and diameter > 0 and (corner_radius is None or corner_radius <= 0):
                corner_radius = diameter / 2.0

        return ToolDefinition(
            number=number,
            tool_type=tool_type,
            diameter=diameter,
            shank_diameter=shank_diameter,
            tip_diameter=tip_diameter,
            corner_radius=corner_radius,
            taper_angle_deg=_taper_angle_from_fields(fields, tool_type),
            length=_positive_or_none(_to_float(fields.get("length"))),
            flute_length=_positive_or_none(_to_float(fields.get("flutelength"))),
            shoulder_length=_positive_or_none(_to_float(fields.get("shoulderlength"))),
            thread_pitch=_positive_or_none(_to_float(fields.get("pitch"))),
            description=fields.get("name", "") or "",
            vendor=fields.get("vendor", "") or "",
            product_id=fields.get("id", "") or "",
            type_name=type_name,
        )
