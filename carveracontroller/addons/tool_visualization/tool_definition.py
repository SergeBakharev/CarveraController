"""Common data structures describing a CNC tool for 3D visualization purposes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ToolType(Enum):
    """Basic tool shapes that can be visualised in the 3D viewer."""

    FLAT_END_MILL = "flat_end_mill"
    BALL_END_MILL = "ball_end_mill"
    BULL_NOSE_END_MILL = "bull_nose_end_mill"
    RADIUS_MILL = "radius_mill"  # Note: Represents a concave radius mill
    CHAMFER_MILL = "chamfer_mill"
    ENGRAVING = "engraving"
    TAPERED_MILL = "tapered_mill"
    LOLLIPOP_MILL = "lollipop_mill"
    THREAD_MILL = "thread_mill"
    DRILL = "drill"
    UNKNOWN = "unknown"


def normalize_tool_type_name(type_name):
    """Normalise a raw tool type name for lookup (strip, lowercase, collapse whitespace)."""
    if not type_name:
        return ""
    return " ".join(type_name.strip().lower().split())


def resolve_tool_type(type_name, name_map):
    """Resolve a raw (untrusted) tool type name to a ToolType using a parser-specific map."""
    normalised = normalize_tool_type_name(type_name)
    if not normalised:
        return ToolType.UNKNOWN
    return name_map.get(normalised, ToolType.UNKNOWN)


@dataclass
class ToolDefinition:
    """Geometry/metadata for a single tool, as extracted from a G-code comment.
    Important: All dimensions are in the same units as the loaded G-code file (mm or in).
    """

    number: int
    tool_type: ToolType = ToolType.UNKNOWN
    diameter: float | None = None
    shank_diameter: float | None = None
    tip_diameter: float | None = None
    corner_radius: float | None = None
    taper_angle_deg: float | None = None  # Angle from the tool axis (per side), matching Fusion's "Taper angle".
    length: float | None = None
    flute_length: float | None = None
    shoulder_length: float | None = None
    thread_depth: float | None = None
    thread_pitch: float | None = None
    description: str = ""
    vendor: str = ""
    product_id: str = ""
    type_name: str = ""
