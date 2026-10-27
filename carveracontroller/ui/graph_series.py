"""Derived monitoring-graph samples that are not a single status field.

Material removal rate assumes a full-diameter slot while the tool center is
inside the stock, and the overlapping width when the center is outside.
Depth is the tool tip's engagement with the stock solid. The result is
cm³/min: mm³/min divided by 1000.
"""

from __future__ import annotations

import math

from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RotaryCylindricalStock, StockShape


def format_graph_value(value: float) -> str:
    """Plain decimal text for hover labels and tick marks.

    Matplotlib's default short formatter prints modest RPM values in scientific
    notation (``5e+02``). Whole numbers stay integers; smaller values keep one
    or two decimal places.
    """
    number = float(value)
    if not math.isfinite(number):
        return ""
    magnitude = abs(number)
    if magnitude >= 100 or number.is_integer():
        return f"{number:.0f}"
    if magnitude >= 10:
        return f"{number:.1f}"
    return f"{number:.2f}"


def rpm_deviation_percent(actual_rpm: float, target_rpm: float) -> float:
    """Signed percent by which actual spindle speed differs from the request.

    Zero when no speed was requested, so a stopped spindle does not divide by zero.
    """
    target = float(target_rpm)
    if target == 0.0:
        return 0.0
    return (float(actual_rpm) - target) / target * 100.0


def tool_cutting_diameter_mm(tool_def, unit_scale: float) -> float | None:
    """Cutting diameter in millimetres, or None when the file did not provide one."""
    diameter = getattr(tool_def, "diameter", None) if tool_def is not None else None
    if diameter is None:
        return None
    try:
        diameter_mm = float(diameter) * float(unit_scale or 1.0)
    except (TypeError, ValueError):
        return None
    if diameter_mm <= 0.0 or not math.isfinite(diameter_mm):
        return None
    return diameter_mm


def tool_flute_length_mm(tool_def, unit_scale: float) -> float | None:
    """Flute length in millimetres when the tool definition includes one."""
    length = getattr(tool_def, "flute_length", None) if tool_def is not None else None
    if length is None:
        return None
    try:
        length_mm = float(length) * float(unit_scale or 1.0)
    except (TypeError, ValueError):
        return None
    if length_mm <= 0.0 or not math.isfinite(length_mm):
        return None
    return length_mm


def material_removal_rate_cm3_per_min(
    *,
    feed_mm_per_min: float,
    tool_diameter_mm: float,
    x_mm: float,
    y_mm: float,
    z_mm: float,
    bounds: StockBounds | None,
    shape: StockShape | None = None,
    flute_length_mm: float | None = None,
) -> float:
    """Volumetric removal rate, or 0 when the tool is not engaged in the stock."""
    if bounds is None or feed_mm_per_min <= 0.0 or tool_diameter_mm <= 0.0:
        return 0.0
    if not all(math.isfinite(value) for value in (feed_mm_per_min, tool_diameter_mm, x_mm, y_mm, z_mm)):
        return 0.0

    if isinstance(shape, RotaryCylindricalStock):
        depth, width = _rotary_engagement_mm(x_mm, y_mm, z_mm, tool_diameter_mm, bounds, shape.diameter_mm)
    elif isinstance(shape, CylindricalStock):
        depth = _axial_depth_mm(z_mm, bounds)
        width = _cylinder_width_of_cut_mm(x_mm, y_mm, tool_diameter_mm, bounds, shape.diameter_mm)
    else:
        depth = _axial_depth_mm(z_mm, bounds)
        width = _rect_width_of_cut_mm(x_mm, y_mm, tool_diameter_mm, bounds)

    if flute_length_mm is not None and flute_length_mm > 0.0:
        depth = min(depth, flute_length_mm)
    if depth <= 0.0 or width <= 0.0:
        return 0.0
    return width * depth * feed_mm_per_min / 1000.0


def _overlap_length(center: float, radius: float, low: float, high: float) -> float:
    return max(0.0, min(center + radius, high) - max(center - radius, low))


def _axial_depth_mm(z_mm: float, bounds: StockBounds) -> float:
    """How much stock is above the tool tip, capped by the stock height."""
    if z_mm >= bounds.max_z:
        return 0.0
    return bounds.max_z - max(z_mm, bounds.min_z)


def _rect_width_of_cut_mm(x_mm: float, y_mm: float, diameter_mm: float, bounds: StockBounds) -> float:
    radius = diameter_mm / 2.0
    overlap_x = _overlap_length(x_mm, radius, bounds.min_x, bounds.max_x)
    overlap_y = _overlap_length(y_mm, radius, bounds.min_y, bounds.max_y)
    if overlap_x <= 0.0 or overlap_y <= 0.0:
        return 0.0
    if bounds.min_x <= x_mm <= bounds.max_x and bounds.min_y <= y_mm <= bounds.max_y:
        return diameter_mm
    return min(overlap_x, overlap_y)


def _cylinder_width_of_cut_mm(
    x_mm: float,
    y_mm: float,
    diameter_mm: float,
    bounds: StockBounds,
    stock_diameter_mm: float,
) -> float:
    radius = diameter_mm / 2.0
    axis_x = 0.5 * (bounds.min_x + bounds.max_x)
    axis_y = 0.5 * (bounds.min_y + bounds.max_y)
    stock_radius = stock_diameter_mm / 2.0
    distance = math.hypot(x_mm - axis_x, y_mm - axis_y)
    if distance >= stock_radius + radius:
        return 0.0
    if distance + radius <= stock_radius:
        return diameter_mm
    return stock_radius + radius - distance


def _rotary_engagement_mm(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    diameter_mm: float,
    bounds: StockBounds,
    stock_diameter_mm: float,
) -> tuple[float, float]:
    """Radial depth into an X-axis bar, and the tool's width along that bar."""
    axis_y = 0.5 * (bounds.min_y + bounds.max_y)
    axis_z = 0.5 * (bounds.min_z + bounds.max_z)
    stock_radius = stock_diameter_mm / 2.0
    depth = stock_radius - math.hypot(y_mm - axis_y, z_mm - axis_z)
    if depth <= 0.0:
        return 0.0, 0.0
    depth = min(depth, stock_diameter_mm)
    radius = diameter_mm / 2.0
    overlap_x = _overlap_length(x_mm, radius, bounds.min_x, bounds.max_x)
    if overlap_x <= 0.0:
        return 0.0, 0.0
    width = diameter_mm if bounds.min_x <= x_mm <= bounds.max_x else overlap_x
    return depth, width
