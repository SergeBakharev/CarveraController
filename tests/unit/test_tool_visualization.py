"""Tests for CAM tool metadata extraction and procedural tool mesh generation."""

import math

import pytest

from carveracontroller.addons.tool_visualization import (
    ToolDefinition,
    ToolType,
    extract_tool_table,
    format_tool_tooltip,
    get_tool_icon_path,
)
from carveracontroller.addons.tool_visualization.mesh_builder import (
    FALLBACK_TOOL_DISPLAY_HEIGHT,
    FALLBACK_TOOL_DISPLAY_RADIUS,
    LENGTH_DIAMETER_FACTOR,
    MIN_VISIBLE_RADIUS,
    VERTEX_FORMAT,
    _reference_length,
    build_tool_mesh,
    build_tool_meshes,
    tool_profile,
)
from carveracontroller.addons.tool_visualization.parsers.fusion360_makera import (
    TOOL_TYPE_NAME_MAP,
    Fusion360MakeraParser,
)
from carveracontroller.addons.tool_visualization.tool_definition import resolve_tool_type


def _max_xy_radius(vertices):
    radii = []
    for i in range(0, len(vertices), 8):
        x = vertices[i]
        y = vertices[i + 1]
        radii.append(math.hypot(x, y))
    return max(radii) if radii else 0.0


def _mesh_height(vertices):
    zs = [vertices[i + 2] for i in range(0, len(vertices), 8)]
    return max(zs) - min(zs) if zs else 0.0


def _apex_vertex_indices(vertices, tol=1e-6):
    zs = [vertices[i + 2] for i in range(0, len(vertices), 8)]
    z_min = min(zs)
    return [
        i // 8
        for i in range(0, len(vertices), 8)
        if abs(vertices[i + 2] - z_min) < tol and math.hypot(vertices[i], vertices[i + 1]) < tol
    ]


class TestFusion360MakeraParser:
    @pytest.fixture
    def parser(self):
        return Fusion360MakeraParser()

    def test_parses_basic_flat_end_mill_comment(self, parser):
        lines = ["(T1  Flat end mill  Vendor  PID  D=6 CR=0 - flat end mill)\n", "G0 X0\n"]
        table = parser.parse(lines)

        assert table[1].number == 1
        assert table[1].tool_type == ToolType.FLAT_END_MILL
        assert table[1].diameter == 6.0
        assert table[1].corner_radius == 0.0
        assert table[1].description == "Flat end mill"
        assert table[1].vendor == "Vendor"
        assert table[1].product_id == "PID"

    def test_parses_optional_taper_and_ignored_zmin(self, parser):
        lines = ["(T2  Bull tool  D=3.175 CR=0.5 TAPER=45deg - ZMIN=-5 - bull nose end mill)\n"]
        table = parser.parse(lines)

        assert table[2].tool_type == ToolType.BULL_NOSE_END_MILL
        assert table[2].taper_angle_deg == 45.0

    def test_parses_tapered_mill_comment(self, parser):
        lines = ["(T12        D=1.872 CR=1. TAPER=3.8deg - ZMIN=-0.7 - tapered mill)\n"]
        table = parser.parse(lines)

        assert table[12].tool_type == ToolType.TAPERED_MILL
        assert table[12].diameter == 1.872
        assert table[12].corner_radius == 1.0
        assert table[12].taper_angle_deg == 3.8
        assert table[12].type_name == "tapered mill"

    def test_parses_semicolon_comments(self, parser):
        lines = [";T3  Thread cutter  D=4 CR=0 - thread mill\n"]
        table = parser.parse(lines)

        assert table[3].tool_type == ToolType.THREAD_MILL

    def test_ignores_duplicate_tool_entries(self, parser):
        lines = [
            "(T1  First  D=6 CR=0 - flat end mill)\n",
            "(T1  Second  D=8 CR=0 - ball end mill)\n",
        ]
        table = parser.parse(lines)

        assert table[1].diameter == 6.0
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_unknown_tool_type_falls_back_to_unknown(self, parser):
        lines = ["(T4  Mystery  D=6 CR=0 - mystery cutter)\n"]
        table = parser.parse(lines)

        assert table[4].tool_type == ToolType.UNKNOWN
        assert table[4].type_name == "mystery cutter"


class TestToolDefinitionHelpers:
    def test_resolve_tool_type_normalises_names(self):
        assert resolve_tool_type("  Flat   End   Mill ", TOOL_TYPE_NAME_MAP) == ToolType.FLAT_END_MILL
        assert resolve_tool_type("", TOOL_TYPE_NAME_MAP) == ToolType.UNKNOWN


class TestIconBuilder:
    def test_default_icon_for_missing_tool(self):
        assert get_tool_icon_path(None) == "data/GcodeViewer/tools/pointed_mill.png"

    def test_maps_known_tool_types(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.BALL_END_MILL)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/ball_end_mill.png"

    def test_maps_tapered_mill_icon(self):
        tool_def = ToolDefinition(number=12, tool_type=ToolType.TAPERED_MILL)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/tapered_mill.png"


class TestTooltipBuilder:
    def test_empty_tooltip_for_missing_tool(self):
        assert format_tool_tooltip(None) == ""

    def test_formats_full_tool_definition(self):
        tool_def = ToolDefinition(
            number=2,
            tool_type=ToolType.BULL_NOSE_END_MILL,
            diameter=6.0,
            corner_radius=0.5,
            taper_angle_deg=5.0,
            description="Roughing endmill",
            vendor="Makera",
            product_id="EM-6-05",
            type_name="Bull nose end mill",
        )
        tooltip = format_tool_tooltip(tool_def)

        assert tooltip == ("T2 - Bull nose end mill\nD=6 CR=0.5 TAPER=5°\nRoughing endmill\nMakera - EM-6-05")

    def test_uses_enum_label_when_type_name_missing(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=3.0)
        assert format_tool_tooltip(tool_def) == "T1 - Flat End Mill\nD=3"


def _vertex_normal(vertices, index):
    base = index * 8
    return (vertices[base + 3], vertices[base + 4], vertices[base + 5])


class TestMeshBuilder:
    def test_build_tool_mesh_uses_expected_vertex_layout(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0)
        vertices, indices, fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // 8

        assert fmt == VERTEX_FORMAT
        assert len(vertices) % 8 == 0
        assert len(indices) % 3 == 0
        assert all(0 <= index < vertex_count for index in indices)
        assert len(indices) > vertex_count

    def test_shared_reference_length_uses_largest_diameter(self):
        tool_table = {
            1: ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=3.0),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=10.0),
        }
        shared_length = _reference_length(tool_table, scale=1.0)

        assert shared_length == 10.0 * LENGTH_DIAMETER_FACTOR
        profile_small = tool_profile(tool_table[1], length=shared_length, scale=1.0)
        profile_large = tool_profile(tool_table[2], length=shared_length, scale=1.0)
        assert profile_small[-1][0] == profile_large[-1][0]

    def test_radius_boost_preserves_relative_sizes(self):
        tool_table = {
            1: ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=0.01),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=1.0),
        }
        meshes, _ = build_tool_meshes(tool_table, scale=0.01)
        small_radius = _max_xy_radius(meshes[1][0])
        large_radius = _max_xy_radius(meshes[2][0])

        assert small_radius >= MIN_VISIBLE_RADIUS
        assert large_radius > small_radius
        assert math.isclose(large_radius / small_radius, 100.0, rel_tol=1e-6)

    def test_default_mesh_unaffected_by_radius_boost(self):
        """Default mesh keeps fixed on-screen size when known tools need boost."""
        tool_table = {
            1: ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=0.01),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=1.0),
        }
        _meshes, default_mesh = build_tool_meshes(tool_table, scale=0.01)
        vertices = default_mesh[0]

        assert _max_xy_radius(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_RADIUS, rel=1e-4)
        assert _mesh_height(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_HEIGHT, rel=1e-4)

    def test_default_mesh_is_generated_for_empty_tool_table(self):
        meshes, default_mesh = build_tool_meshes({})

        assert meshes == {}
        assert len(default_mesh[0]) > 0
        assert len(default_mesh[1]) > 0

    @pytest.mark.parametrize("scale", [0.02, 0.5, 1.0, 2.0])
    def test_fallback_mesh_has_fixed_display_size(self, scale):
        """No-metadata fallback keeps a constant on-screen footprint."""
        _meshes, default_mesh = build_tool_meshes({}, scale=scale)
        vertices = default_mesh[0]

        assert _max_xy_radius(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_RADIUS, rel=1e-4)
        assert _mesh_height(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_HEIGHT, rel=1e-4)

    @pytest.mark.parametrize("scale", [0.02, 0.5])
    def test_missing_diameter_uses_fixed_display_size(self, scale):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=None)
        meshes, _ = build_tool_meshes({1: tool_def}, scale=scale)
        vertices = meshes[1][0]

        assert _max_xy_radius(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_RADIUS, rel=1e-4)
        assert _mesh_height(vertices) == pytest.approx(FALLBACK_TOOL_DISPLAY_HEIGHT, rel=1e-4)

    def test_ball_end_mill_profile_has_more_detail_than_flat_end_mill(self):
        shared_length = 18.0
        flat_profile = tool_profile(
            ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0),
            length=shared_length,
        )
        ball_profile = tool_profile(
            ToolDefinition(number=2, tool_type=ToolType.BALL_END_MILL, diameter=6.0),
            length=shared_length,
        )

        assert flat_profile[0] == (0.0, 3.0)
        assert ball_profile[0][0] == pytest.approx(0.0)
        assert ball_profile[0][1] == pytest.approx(0.0)
        assert ball_profile[-1][0] == flat_profile[-1][0]
        assert len(ball_profile) > len(flat_profile)

    def test_build_tool_meshes_scales_geometry(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0)
        mesh_a, _ = build_tool_meshes({1: tool_def}, scale=1.0)
        mesh_b, _ = build_tool_meshes({1: tool_def}, scale=2.0)

        assert _mesh_height(mesh_b[1][0]) == pytest.approx(_mesh_height(mesh_a[1][0]) * 2.0)

    def test_flat_end_mill_side_normals_are_radial(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0)
        vertices, indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // 8

        assert vertex_count < len(indices)

        for index in range(vertex_count):
            nx, ny, nz = _vertex_normal(vertices, index)
            length = math.hypot(nx, ny, nz)
            assert length == pytest.approx(1.0, abs=1e-6)
            if abs(nz) < 0.5:
                assert abs(nz) == pytest.approx(0.0, abs=1e-6)
                assert math.hypot(nx, ny) == pytest.approx(1.0, abs=1e-6)

    def test_ball_end_mill_reuses_vertices_across_triangles(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.BALL_END_MILL, diameter=6.0)
        vertices, indices, _fmt = build_tool_mesh(tool_def)

        assert len(indices) > len(vertices) // 8

    def test_pointed_tip_mesh_shares_single_apex_vertex(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.CHAMFER_MILL, diameter=6.0)
        vertices, _indices, _fmt = build_tool_mesh(tool_def)

        assert len(_apex_vertex_indices(vertices)) == 1

    @pytest.mark.parametrize(
        "tool_type",
        [
            ToolType.BULL_NOSE_END_MILL,
            ToolType.RADIUS_MILL,
            ToolType.CHAMFER_MILL,
            ToolType.TAPERED_MILL,
            ToolType.LOLLIPOP_MILL,
            ToolType.THREAD_MILL,
        ],
    )
    def test_tool_profiles_have_expected_shape(self, tool_type):
        diameter = 6.0
        shared_length = diameter * LENGTH_DIAMETER_FACTOR
        profile = tool_profile(
            ToolDefinition(number=1, tool_type=tool_type, diameter=diameter, corner_radius=0.5),
            length=shared_length,
        )

        assert profile[-1][0] == shared_length

        if tool_type == ToolType.BULL_NOSE_END_MILL:
            assert profile[0][1] < diameter / 2.0
            assert len(profile) > 2
        elif tool_type == ToolType.RADIUS_MILL:
            corner_radius = 0.5
            assert profile[0] == (0.0, pytest.approx(diameter / 2.0))
            assert profile[-1][1] == pytest.approx(diameter / 2.0 + corner_radius)
            assert len(profile) > 2
        elif tool_type == ToolType.CHAMFER_MILL:
            assert profile[0] == (0.0, 0.0)
            assert len(profile) >= 2
        elif tool_type == ToolType.TAPERED_MILL:
            # Tip diameter D with a bull-nose corner; sides widen above the tip.
            assert profile[0][0] == pytest.approx(0.0)
            assert 0.0 < profile[0][1] < diameter / 2.0
            assert profile[-1][1] > diameter / 2.0
            assert len(profile) > 3
        elif tool_type == ToolType.LOLLIPOP_MILL:
            assert len(profile) > 4
            assert profile[0] == (0.0, pytest.approx(0.0))
            assert max(r for _, r in profile) == pytest.approx(diameter / 2.0)
            # Neck is a plain cylinder: last two points share the undercut radius.
            assert profile[-1][1] < diameter / 2.0
            assert profile[-2][1] == pytest.approx(profile[-1][1])
            assert profile[-1][0] == shared_length
        elif tool_type == ToolType.THREAD_MILL:
            assert profile[0][1] < diameter / 2.0
            assert max(r for _, r in profile) == pytest.approx(diameter / 2.0)
            assert len(profile) >= 3

    def test_tapered_mill_is_bull_nose_tip_with_taper(self):
        diameter = 6.0
        corner_radius = 1.0
        taper_angle_deg = 30.0
        shared_length = diameter * LENGTH_DIAMETER_FACTOR
        profile = tool_profile(
            ToolDefinition(
                number=12,
                tool_type=ToolType.TAPERED_MILL,
                diameter=diameter,
                corner_radius=corner_radius,
                taper_angle_deg=taper_angle_deg,
            ),
            length=shared_length,
        )

        alpha = math.radians(taper_angle_deg)
        flat_radius = diameter / 2.0 - corner_radius * math.cos(alpha)
        z_tan = corner_radius * (1.0 - math.sin(alpha))
        r_tan = diameter / 2.0
        end_radius = r_tan + (shared_length - z_tan) * math.tan(alpha)

        assert profile[0] == (0.0, pytest.approx(flat_radius))
        assert any(math.isclose(z, z_tan, abs_tol=1e-6) and math.isclose(r, r_tan, abs_tol=1e-6) for z, r in profile)
        assert profile[-1][0] == pytest.approx(shared_length)
        assert profile[-1][1] == pytest.approx(end_radius)
        assert profile[-1][1] > diameter / 2.0

    def test_tapered_mill_without_corner_radius_has_flat_tip(self):
        diameter = 6.0
        taper_angle_deg = 30.0
        shared_length = diameter * LENGTH_DIAMETER_FACTOR
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.TAPERED_MILL,
                diameter=diameter,
                corner_radius=0.0,
                taper_angle_deg=taper_angle_deg,
            ),
            length=shared_length,
        )

        tip_radius = diameter / 2.0
        end_radius = tip_radius + shared_length * math.tan(math.radians(taper_angle_deg))
        assert profile[0] == (0.0, tip_radius)
        assert profile[-1][0] == pytest.approx(shared_length)
        assert profile[-1][1] == pytest.approx(end_radius)

    def test_tapered_mill_with_zero_taper_matches_bull_nose(self):
        diameter = 6.0
        corner_radius = 1.0
        shared_length = diameter * LENGTH_DIAMETER_FACTOR
        tapered = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.TAPERED_MILL,
                diameter=diameter,
                corner_radius=corner_radius,
                taper_angle_deg=0.0,
            ),
            length=shared_length,
        )
        bull = tool_profile(
            ToolDefinition(
                number=2,
                tool_type=ToolType.BULL_NOSE_END_MILL,
                diameter=diameter,
                corner_radius=corner_radius,
            ),
            length=shared_length,
        )

        assert tapered[0] == bull[0]
        assert tapered[-1] == bull[-1]
        assert len(tapered) == len(bull)
        for (z0, r0), (z1, r1) in zip(tapered, bull):
            assert z0 == pytest.approx(z1)
            assert r0 == pytest.approx(r1)

    def test_radius_mill_interprets_diameter_as_flat_bottom(self):
        profile = tool_profile(
            ToolDefinition(number=2, tool_type=ToolType.RADIUS_MILL, diameter=2.0, corner_radius=2.0),
            length=20.0,
        )

        assert profile[0] == (0.0, 1.0)
        assert profile[-1][1] == pytest.approx(3.0)

    def test_radius_mill_corner_arc_is_reversed_from_bull_nose(self):
        flat_diameter = 4.0
        full_diameter = 6.0
        corner_radius = 1.0
        shared_length = full_diameter * LENGTH_DIAMETER_FACTOR
        radius_profile = tool_profile(
            ToolDefinition(
                number=1, tool_type=ToolType.RADIUS_MILL, diameter=flat_diameter, corner_radius=corner_radius
            ),
            length=shared_length,
        )
        bull_profile = tool_profile(
            ToolDefinition(
                number=2, tool_type=ToolType.BULL_NOSE_END_MILL, diameter=full_diameter, corner_radius=corner_radius
            ),
            length=shared_length,
        )

        assert radius_profile[0] == bull_profile[0]
        assert radius_profile[-1] == bull_profile[-1]

        mid_z = corner_radius / 2.0
        full_radius = full_diameter / 2.0
        radius_mid_r = full_radius + corner_radius * math.cos(5.0 * math.pi / 6.0)
        bull_mid_r = (full_radius - corner_radius) + corner_radius * math.cos(-math.pi / 6.0)
        profile_radius_mid_r = min(radius_profile, key=lambda point: abs(point[0] - mid_z))[1]
        profile_bull_mid_r = min(bull_profile, key=lambda point: abs(point[0] - mid_z))[1]

        assert profile_radius_mid_r == pytest.approx(radius_mid_r, abs=0.05)
        assert profile_bull_mid_r == pytest.approx(bull_mid_r, abs=0.05)
        assert profile_radius_mid_r < profile_bull_mid_r


class TestExtractor:
    def test_extract_tool_table_returns_first_non_empty_parser_result(self):
        lines = ["(T1  End mill  D=6 CR=0 - flat end mill)\n", "G0 X0\n"]
        table = extract_tool_table(lines)

        assert 1 in table
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_extract_tool_table_returns_empty_dict_when_unrecognised(self):
        lines = ["G0 X0 Y0\n", "G1 X1 F100\n"]
        assert extract_tool_table(lines) == {}
