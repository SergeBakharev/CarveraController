"""Tool metadata extraction and 3D mesh generation for the G-code viewer.

This package parses CAM-generated comments in loaded G-code files to build a
per-tool description (type + geometry), then generates a basic 3D mesh for
each tool so the viewer can display a shape that roughly matches the tool
that is currently active instead of a single generic cylinder.
"""

from carveracontroller.addons.tool_visualization.extractor import extract_tool_table
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType
from carveracontroller.addons.tool_visualization.tooltip_builder import format_tool_tooltip

__all__ = [
    "extract_tool_table",
    "format_tool_tooltip",
    "ToolDefinition",
    "ToolType",
]
