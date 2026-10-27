"""Derived monitoring series: spindle deviation and material removal rate."""

from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import CylindricalStock, RectangularStock, RotaryCylindricalStock
from carveracontroller.ui.graph_series import (
    format_graph_value,
    material_removal_rate_cm3_per_min,
    rpm_deviation_percent,
    tool_cutting_diameter_mm,
)


class _Tool:
    def __init__(self, diameter=None, flute_length=None):
        self.diameter = diameter
        self.flute_length = flute_length


def test_graph_values_are_not_written_in_scientific_notation():
    assert format_graph_value(0) == "0"
    assert format_graph_value(500) == "500"
    assert format_graph_value(5e2) == "500"
    assert format_graph_value(10000) == "10000"
    assert format_graph_value(-5.25) == "-5.25"
    assert format_graph_value(42.1) == "42.1"


def test_rpm_deviation_percent_is_signed_against_the_request():
    assert rpm_deviation_percent(9500, 10000) == -5.0
    assert rpm_deviation_percent(11000, 10000) == 10.0


def test_rpm_deviation_is_zero_when_no_speed_was_requested():
    assert rpm_deviation_percent(0, 0) == 0.0
    assert rpm_deviation_percent(12000, 0) == 0.0


def test_tool_diameter_requires_an_explicit_positive_value():
    assert tool_cutting_diameter_mm(_Tool(diameter=6), 1.0) == 6.0
    assert tool_cutting_diameter_mm(_Tool(diameter=0.25), 25.4) == 6.35
    assert tool_cutting_diameter_mm(_Tool(), 1.0) is None
    assert tool_cutting_diameter_mm(None, 1.0) is None


def _block() -> tuple[RectangularStock, StockBounds]:
    shape = RectangularStock(width_mm=100, length_mm=80, height_mm=20)
    bounds = StockBounds(min_x=0, min_y=0, min_z=0, max_x=100, max_y=80, max_z=20)
    return shape, bounds


def test_mrr_for_a_slot_inside_rectangular_stock():
    shape, bounds = _block()
    # 10 mm tool, 2 mm deep, 1000 mm/min → 20 cm³/min.
    rate = material_removal_rate_cm3_per_min(
        feed_mm_per_min=1000,
        tool_diameter_mm=10,
        x_mm=50,
        y_mm=40,
        z_mm=18,
        bounds=bounds,
        shape=shape,
    )
    assert rate == 20.0


def test_mrr_is_zero_when_the_tool_is_clear_of_the_stock():
    shape, bounds = _block()
    above = material_removal_rate_cm3_per_min(
        feed_mm_per_min=1000,
        tool_diameter_mm=10,
        x_mm=50,
        y_mm=40,
        z_mm=25,
        bounds=bounds,
        shape=shape,
    )
    outside = material_removal_rate_cm3_per_min(
        feed_mm_per_min=1000,
        tool_diameter_mm=10,
        x_mm=-30,
        y_mm=40,
        z_mm=10,
        bounds=bounds,
        shape=shape,
    )
    assert above == 0.0
    assert outside == 0.0


def test_mrr_uses_the_overlapping_width_when_the_center_is_outside():
    shape, bounds = _block()
    # 10 mm tool centered 2 mm outside the stock overlaps by 3 mm, 2 mm deep.
    rate = material_removal_rate_cm3_per_min(
        feed_mm_per_min=1000,
        tool_diameter_mm=10,
        x_mm=-2,
        y_mm=40,
        z_mm=18,
        bounds=bounds,
        shape=shape,
    )
    assert rate == 6.0


def test_mrr_ignores_the_square_corners_of_round_stock():
    shape = CylindricalStock(diameter_mm=20, height_mm=30)
    bounds = StockBounds(min_x=0, min_y=0, min_z=0, max_x=20, max_y=20, max_z=30)
    corner = material_removal_rate_cm3_per_min(
        feed_mm_per_min=500,
        tool_diameter_mm=6,
        x_mm=0,
        y_mm=0,
        z_mm=20,
        bounds=bounds,
        shape=shape,
    )
    center = material_removal_rate_cm3_per_min(
        feed_mm_per_min=500,
        tool_diameter_mm=6,
        x_mm=10,
        y_mm=10,
        z_mm=28,
        bounds=bounds,
        shape=shape,
    )
    assert corner == 0.0
    assert center == 6.0


def test_mrr_for_a_radial_cut_into_rotary_stock():
    shape = RotaryCylindricalStock(diameter_mm=20, length_mm=100)
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=100, max_y=10, max_z=10)
    # Tip 2 mm under the bar surface, 10 mm tool, 600 mm/min → 12 cm³/min.
    rate = material_removal_rate_cm3_per_min(
        feed_mm_per_min=600,
        tool_diameter_mm=10,
        x_mm=50,
        y_mm=0,
        z_mm=8,
        bounds=bounds,
        shape=shape,
    )
    assert rate == 12.0


def test_mrr_is_capped_by_flute_length():
    shape, bounds = _block()
    rate = material_removal_rate_cm3_per_min(
        feed_mm_per_min=1000,
        tool_diameter_mm=10,
        x_mm=50,
        y_mm=40,
        z_mm=0,
        bounds=bounds,
        shape=shape,
        flute_length_mm=1,
    )
    assert rate == 10.0
