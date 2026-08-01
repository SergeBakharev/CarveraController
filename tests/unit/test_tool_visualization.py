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
    FALLBACK_FLUTE_DIAMETER_FACTOR,
    FALLBACK_TOOL_DISPLAY_HEIGHT,
    FALLBACK_TOOL_DISPLAY_RADIUS,
    FLOATS_PER_VERTEX,
    FLUTE_COLOR,
    INFERRED_SHOULDER_DIAMETER_FACTOR,
    LENGTH_DIAMETER_FACTOR,
    MIN_VISIBLE_RADIUS,
    SHANK_COLOR,
    VERTEX_FORMAT,
    build_tool_mesh,
    build_tool_meshes,
    tool_profile,
)
from carveracontroller.addons.tool_visualization.parsers.freecad_makera import (
    TOOL_TYPE_NAME_MAP as FREECAD_MAKERA_TOOL_TYPE_NAME_MAP,
)
from carveracontroller.addons.tool_visualization.parsers.freecad_makera import (
    FreeCADMakeraParser,
)
from carveracontroller.addons.tool_visualization.parsers.fusion360_makera import (
    TOOL_TYPE_NAME_MAP,
    Fusion360MakeraParser,
    _infer_shank_diameter,
)
from carveracontroller.addons.tool_visualization.parsers.makera_studio import (
    TOOL_TYPE_NAME_MAP as MAKERA_STUDIO_TOOL_TYPE_NAME_MAP,
)
from carveracontroller.addons.tool_visualization.parsers.makera_studio import (
    MakeraStudioParser,
)
from carveracontroller.addons.tool_visualization.tool_definition import resolve_tool_type
from carveracontroller.CNC import unit_scale_to_mm


def _max_xy_radius(vertices):
    radii = []
    for i in range(0, len(vertices), FLOATS_PER_VERTEX):
        x = vertices[i]
        y = vertices[i + 1]
        radii.append(math.hypot(x, y))
    return max(radii) if radii else 0.0


def _mesh_height(vertices):
    zs = [vertices[i + 2] for i in range(0, len(vertices), FLOATS_PER_VERTEX)]
    return max(zs) - min(zs) if zs else 0.0


def _apex_vertex_indices(vertices, tol=1e-6):
    zs = [vertices[i + 2] for i in range(0, len(vertices), FLOATS_PER_VERTEX)]
    z_min = min(zs)
    return [
        i // FLOATS_PER_VERTEX
        for i in range(0, len(vertices), FLOATS_PER_VERTEX)
        if abs(vertices[i + 2] - z_min) < tol and math.hypot(vertices[i], vertices[i + 1]) < tol
    ]


def _vertex_normal(vertices, index):
    base = index * FLOATS_PER_VERTEX
    return (vertices[base + 3], vertices[base + 4], vertices[base + 5])


def _vertex_color(vertices, index):
    base = index * FLOATS_PER_VERTEX
    return (vertices[base + 6], vertices[base + 7], vertices[base + 8], vertices[base + 9])


def _vertex_z(vertices, index):
    return vertices[index * FLOATS_PER_VERTEX + 2]


class TestFusion360MakeraParser:
    @pytest.fixture
    def parser(self):
        return Fusion360MakeraParser()

    def test_parses_basic_flat_end_mill_comment(self, parser):
        lines = ["(T1  Flat end mill  Vendor  PID  D=6 - flat end mill)\n", "G0 X0\n"]
        table = parser.parse(lines)

        assert table[1].number == 1
        assert table[1].tool_type == ToolType.FLAT_END_MILL
        assert table[1].diameter == 6.0
        assert table[1].shank_diameter == 6.0
        assert table[1].corner_radius is None
        assert table[1].description == "Flat end mill"
        assert table[1].vendor == "Vendor"
        assert table[1].product_id == "PID"
        assert table[1].length is None
        assert table[1].flute_length is None
        assert table[1].tip_diameter is None

    def test_parses_optional_taper_and_ignored_zmin(self, parser):
        lines = ["(T2  Bull tool  D=3.175 CR=0.5 TAPER=45deg - ZMIN=-5 - bull nose end mill)\n"]
        table = parser.parse(lines)

        assert table[2].tool_type == ToolType.BULL_NOSE_END_MILL
        assert table[2].taper_angle_deg == 45.0
        assert table[2].shank_diameter == 3.175

    def test_parses_tapered_mill_comment(self, parser):
        lines = ["(T12        D=1.872 CR=1. TAPER=3.8deg - ZMIN=-0.7 - tapered mill)\n"]
        table = parser.parse(lines)

        assert table[12].tool_type == ToolType.TAPERED_MILL
        assert table[12].diameter == 1.872
        assert table[12].corner_radius == 1.0
        assert table[12].taper_angle_deg == 3.8
        assert table[12].type_name == "tapered mill"
        assert table[12].shank_diameter is None

    def test_infers_radius_mill_shank_from_outer_diameter(self, parser):
        lines = ["(T5  Concave  D=2 CR=2 - radius mill)\n"]
        table = parser.parse(lines)

        assert table[5].tool_type == ToolType.RADIUS_MILL
        assert table[5].shank_diameter == 6.0

    def test_chamfer_mill_keeps_chamfer_type(self, parser):
        lines = ["(T1  Single Flute Engraving Metal 60 deg*.1mm      D=3.175 TAPER=30deg - ZMIN=0. - chamfer mill)\n"]
        table = parser.parse(lines)

        assert table[1].tool_type == ToolType.CHAMFER_MILL
        assert table[1].shank_diameter == 3.175
        assert table[1].taper_angle_deg == 30.0

    def test_lollipop_leaves_shank_unset(self, parser):
        lines = ["(T8  Under  D=6 - lollipop mill)\n"]
        table = parser.parse(lines)

        assert table[8].tool_type == ToolType.LOLLIPOP_MILL
        assert table[8].shank_diameter is None

    def test_parses_semicolon_comments(self, parser):
        lines = [";T3  Thread cutter  D=4 - thread mill\n"]
        table = parser.parse(lines)

        assert table[3].tool_type == ToolType.THREAD_MILL
        assert table[3].shank_diameter == 4.0

    def test_ignores_duplicate_tool_entries(self, parser):
        lines = [
            "(T1  First  D=6 - flat end mill)\n",
            "(T1  Second  D=8 - ball end mill)\n",
        ]
        table = parser.parse(lines)

        assert table[1].diameter == 6.0
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_unknown_tool_type_falls_back_to_unknown(self, parser):
        lines = ["(T4  Mystery  D=6 - mystery cutter)\n"]
        table = parser.parse(lines)

        assert table[4].tool_type == ToolType.UNKNOWN
        assert table[4].type_name == "mystery cutter"
        assert table[4].shank_diameter == 6.0

    def test_parses_extended_geometry_fields(self, parser):
        lines = ["(T7  Chamfer  Vendor  PID  D=6 SD=6 TD=0.2 FL=8 SL=12 BL=20 TAPER=45deg - ZMIN=-1 - chamfer mill)\n"]
        table = parser.parse(lines)

        tool = table[7]
        assert tool.tool_type == ToolType.CHAMFER_MILL
        assert tool.diameter == 6.0
        assert tool.shank_diameter == 6.0
        assert tool.tip_diameter == 0.2
        assert tool.flute_length == 8.0
        assert tool.shoulder_length == 12.0
        assert tool.length == 20.0
        assert tool.taper_angle_deg == 45.0
        assert tool.vendor == "Vendor"
        assert tool.product_id == "PID"

    def test_parses_thread_pitch_field(self, parser):
        lines = ["(T9  Thread  D=4 FL=10 TP=0.75 - thread mill)\n"]
        table = parser.parse(lines)

        assert table[9].tool_type == ToolType.THREAD_MILL
        assert table[9].thread_pitch == 0.75
        assert table[9].flute_length == 10.0

    def test_explicit_shaft_overrides_inference_for_lollipop(self, parser):
        lines = ["(T8  Under  D=6 SD=4 - lollipop mill)\n"]
        table = parser.parse(lines)

        assert table[8].tool_type == ToolType.LOLLIPOP_MILL
        assert table[8].shank_diameter == 4.0

    def test_legacy_cr_zero_still_parses(self, parser):
        lines = ["(T1  Flat  D=6 CR=0 - flat end mill)\n"]
        table = parser.parse(lines)

        assert table[1].corner_radius == 0.0
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_parses_drill_with_included_tip_angle(self, parser):
        lines = [
            "(T5  3*12mm Drill  Makera    D=3. SD=3. TD=0. FL=12. SL=12. BL=26. TAPER=118deg - ZMIN=-25.67 - drill)\n"
        ]
        table = parser.parse(lines)

        tool = table[5]
        assert tool.tool_type == ToolType.DRILL
        assert tool.diameter == 3.0
        assert tool.shank_diameter == 3.0
        assert tool.tip_diameter == 0.0
        assert tool.flute_length == 12.0
        assert tool.shoulder_length == 12.0
        assert tool.length == 26.0
        assert tool.taper_angle_deg == 59.0  # included 118° → per-side 59°
        assert tool.description == "3*12mm Drill"
        assert tool.vendor == "Makera"
        assert tool.type_name == "drill"


class TestMakeraStudioParser:
    @pytest.fixture
    def parser(self):
        return MakeraStudioParser()

    def test_parses_sample_flat_end_header(self, parser):
        lines = [
            ";@MKR|BEGIN\n",
            ";@MKR|SCHEMA|v=1.0.0\n",
            ";@MKR|TOOL|number=1|id=111011203812|name=3.175*2*12mm Flat End|type=Flat End|"
            "handlediameter=3.175|sticklength=0|shoulderlength=12|flutelength=12|diameter=2|"
            "tipdiameter=2|cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|END\n",
            "G0 X0\n",
        ]
        table = parser.parse(lines)

        tool = table[1]
        assert tool.tool_type == ToolType.FLAT_END_MILL
        assert tool.diameter == 2.0
        assert tool.shank_diameter == 3.175
        assert tool.tip_diameter == 2.0
        assert tool.corner_radius == 0.0
        assert tool.length == 12.0
        assert tool.flute_length == 12.0
        assert tool.shoulder_length == 12.0
        assert tool.description == "3.175*2*12mm Flat End"
        assert tool.product_id == "111011203812"
        assert tool.type_name == "Flat End"
        assert tool.taper_angle_deg is None

    def test_parses_distinct_flute_shoulder_and_stick_lengths(self, parser):
        lines = [
            ";@MKR|TOOL|number=1|id=111011203812|name=3.175*2*12mm Flat End|type=Flat End|"
            "handlediameter=3.175|sticklength=12|shoulderlength=6|flutelength=6|diameter=2|"
            "tipdiameter=2|cornerradius=0|angle=0|halfAngle=0\n"
        ]
        tool = parser.parse(lines)[1]

        assert tool.diameter == 2.0
        assert tool.shank_diameter == 3.175
        assert tool.flute_length == 6.0
        assert tool.shoulder_length == 6.0
        assert tool.length == 12.0

    def test_parses_shoulder_equal_to_stick_without_shank_body(self, parser):
        lines = [
            ";@MKR|TOOL|number=1|id=111011203812|name=3.175*2*12mm Flat End|type=Flat End|"
            "handlediameter=3.175|sticklength=12|shoulderlength=12|flutelength=6|diameter=2|"
            "tipdiameter=2|cornerradius=0|angle=0|halfAngle=0\n"
        ]
        tool = parser.parse(lines)[1]

        assert tool.flute_length == 6.0
        assert tool.shoulder_length == 12.0
        assert tool.length == 12.0

    def test_parses_engraving_half_angle_as_per_side_taper(self, parser):
        lines = [
            ";@MKR|TOOL|number=2|id=abc|name=V-bit|type=Engraving|handlediameter=3.175|"
            "sticklength=20|shoulderlength=0|flutelength=12|diameter=3.175|tipdiameter=0.1|"
            "cornerradius=0|angle=0|halfAngle=15\n"
        ]
        table = parser.parse(lines)

        tool = table[2]
        assert tool.tool_type == ToolType.ENGRAVING
        assert tool.taper_angle_deg == 15.0
        assert tool.tip_diameter == 0.1
        assert tool.length == 20.0
        assert tool.flute_length == 12.0
        assert tool.shoulder_length is None
        assert tool.shank_diameter == 3.175

    def test_parses_engraving_included_angle_as_per_side_taper(self, parser):
        lines = [
            ";@MKR|TOOL|number=3|id=abc|name=V-bit|type=Engraving|handlediameter=3.175|"
            "sticklength=20|shoulderlength=0|flutelength=12|diameter=3.175|tipdiameter=0.1|"
            "cornerradius=0|angle=60|halfAngle=0\n"
        ]
        tool = parser.parse(lines)[3]
        assert tool.taper_angle_deg == 30.0

    def test_parses_complex_makera_studio_tool_header(self, parser):
        lines = [
            ";@MKR|TOOL|number=1|id=112111203808|name=3.175*2*8mm Flat End(Metal)|type=Flat End|"
            "handlediameter=3.175|sticklength=0|shoulderlength=8|flutelength=8|diameter=2|"
            "tipdiameter=2|cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|TOOL|number=2|id=142212313812|name=3.175*12mm Drill|type=Drill|"
            "handlediameter=3.175|sticklength=0|shoulderlength=12|flutelength=12|diameter=3.175|"
            "tipdiameter=3.175|cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|TOOL|number=3|id=152111243809|name=3.175*M3*9mm Thread|type=Thread|"
            "handlediameter=3.175|sticklength=0|shoulderlength=9|flutelength=10|diameter=2.42|"
            "tipdiameter=0|cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|TOOL|number=4|id=122111013890|name=3.175mm*90º Chamfer|type=V-Bit|"
            "handlediameter=3.175|sticklength=0|shoulderlength=0|flutelength=1.6|diameter=3.175|"
            "tipdiameter=0.1|cornerradius=0|angle=90|halfAngle=0\n",
            ";@MKR|TOOL|number=5|id=112131605017|name=6*17mm Flat End(Metal)|type=Flat End|"
            "handlediameter=6|sticklength=0|shoulderlength=17|flutelength=17|diameter=6|"
            "tipdiameter=6|cornerradius=0|angle=0|halfAngle=0\n",
        ]
        table = parser.parse(lines)

        assert set(table) == {1, 2, 3, 4, 5}

        flat = table[1]
        assert flat.tool_type == ToolType.FLAT_END_MILL
        assert flat.diameter == 2.0
        assert flat.shank_diameter == 3.175
        assert flat.length == 8.0
        assert flat.product_id == "112111203808"

        drill = table[2]
        assert drill.tool_type == ToolType.DRILL
        assert drill.diameter == 3.175
        assert drill.shank_diameter == 3.175
        assert drill.length == 12.0
        assert drill.type_name == "Drill"

        thread = table[3]
        assert thread.tool_type == ToolType.THREAD_MILL
        assert thread.diameter == 2.42
        assert thread.flute_length == 10.0
        assert thread.shoulder_length == 9.0
        assert thread.length == 9.0
        assert thread.tip_diameter == 0.0

        vbit = table[4]
        assert vbit.tool_type == ToolType.CHAMFER_MILL
        assert vbit.type_name == "V-Bit"
        assert vbit.tip_diameter == 0.1
        assert vbit.taper_angle_deg == 45.0  # included 90° → per-side 45°
        assert vbit.flute_length == 1.6
        assert vbit.shoulder_length is None
        assert vbit.length is None

        flat6 = table[5]
        assert flat6.tool_type == ToolType.FLAT_END_MILL
        assert flat6.diameter == 6.0
        assert flat6.shank_diameter == 6.0
        assert flat6.length == 17.0

    def test_maps_ball_nose_and_tapered_ball_nose(self, parser):
        lines = [
            ";@MKR|TOOL|number=1|id=a|name=Ball|type=Ball Nose|handlediameter=3.175|"
            "sticklength=0|shoulderlength=12|flutelength=12|diameter=2|tipdiameter=2|"
            "cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|TOOL|number=2|id=b|name=Tapered|type=Tapered Ball Nose|handlediameter=6|"
            "sticklength=0|shoulderlength=20|flutelength=15|diameter=2|tipdiameter=2|"
            "cornerradius=0|angle=10|halfAngle=0\n",
            ";@MKR|TOOL|number=3|id=c|name=Bull|type=Bull Nose|handlediameter=6|"
            "sticklength=0|shoulderlength=20|flutelength=15|diameter=6|tipdiameter=6|"
            "cornerradius=1|angle=0|halfAngle=0\n",
        ]
        table = parser.parse(lines)

        assert table[1].tool_type == ToolType.BALL_END_MILL
        assert table[2].tool_type == ToolType.TAPERED_MILL
        assert table[2].corner_radius == 1.0  # inferred D/2 for ball tip
        assert table[2].taper_angle_deg == 5.0  # included 10° → per-side 5°
        assert table[3].tool_type == ToolType.BULL_NOSE_END_MILL
        assert table[3].corner_radius == 1.0

    def test_unknown_type_falls_back_to_unknown(self, parser):
        lines = [";@MKR|TOOL|number=3|id=x|name=Mystery|type=Mystery Cutter|diameter=6|cornerradius=0\n"]
        table = parser.parse(lines)

        assert table[3].tool_type == ToolType.UNKNOWN
        assert table[3].type_name == "Mystery Cutter"

    def test_returns_empty_for_non_mkr_header(self, parser):
        lines = ["(T1  Flat end mill  D=6 CR=0 - flat end mill)\n", "G0 X0\n"]
        assert parser.parse(lines) == {}


class TestFreeCADMakeraParser:
    @pytest.fixture
    def parser(self):
        return FreeCADMakeraParser()

    def test_parses_sample_flat_end_header(self, parser):
        lines = [
            "(Exported by FreeCAD)\n",
            "(@FC|TOOL|number=1|name=Spiral O 1.5*8mm|vendor=Makera|type=Endmill|"
            "diameter=1.5|shankdiameter=3.175|flutelength=8|length=38)\n",
            "G0 X0\n",
        ]
        table = parser.parse(lines)

        tool = table[1]
        assert tool.tool_type == ToolType.FLAT_END_MILL
        assert tool.diameter == 1.5
        assert tool.shank_diameter == 3.175
        assert tool.flute_length == 8.0
        assert tool.length == 38.0
        assert tool.description == "Spiral O 1.5*8mm"
        assert tool.vendor == "Makera"
        assert tool.type_name == "Endmill"
        assert tool.taper_angle_deg is None

    def test_parses_drill_tip_angle_as_per_side(self, parser):
        lines = [
            "(@FC|TOOL|number=2|name=2.3*12mm Drill|vendor=Makera|type=Drill|"
            "diameter=2.3|shankdiameter=3.175|flutelength=12|length=38|tipangle=118)\n"
        ]
        tool = parser.parse(lines)[2]

        assert tool.tool_type == ToolType.DRILL
        assert tool.diameter == 2.3
        assert tool.taper_angle_deg == 59.0
        assert tool.flute_length == 12.0

    def test_ignores_invalid_cutting_edge_angle_over_180(self, parser):
        lines = ["(@FC|TOOL|number=2|name=Drill|type=Drill|diameter=2.3|cuttingedgeangle=236)\n"]
        tool = parser.parse(lines)[2]
        assert tool.taper_angle_deg is None

    def test_parses_chamfer_included_cutting_edge_angle(self, parser):
        lines = [
            "(@FC|TOOL|number=4|name=Chamfering Bit|vendor=Makera|type=Chamfer|"
            "diameter=3.175|shankdiameter=3.175|tipdiameter=0.1|flutelength=3|length=38|"
            "cuttingedgeangle=90)\n"
        ]
        tool = parser.parse(lines)[4]

        assert tool.tool_type == ToolType.CHAMFER_MILL
        assert tool.tip_diameter == 0.1
        assert tool.taper_angle_deg == 45.0

    def test_parses_vbit_as_chamfer(self, parser):
        lines = ["(@FC|TOOL|number=5|name=Engraving|type=VBit|diameter=3.175|tipdiameter=0.1|cuttingedgeangle=30)\n"]
        tool = parser.parse(lines)[5]
        assert tool.tool_type == ToolType.CHAMFER_MILL
        assert tool.taper_angle_deg == 15.0

    def test_parses_thread_mill_pitch(self, parser):
        lines = [
            "(@FC|TOOL|number=3|name=M3 Threadmill|type=ThreadMill|diameter=2.42|"
            "shankdiameter=3.175|flutelength=9|length=38|pitch=0.5)\n"
        ]
        tool = parser.parse(lines)[3]

        assert tool.tool_type == ToolType.THREAD_MILL
        assert tool.thread_pitch == 0.5
        assert tool.diameter == 2.42

    def test_parses_ball_end_and_tapered_ball_nose(self, parser):
        lines = [
            "(@FC|TOOL|number=1|name=Ball|type=Ballend|diameter=4|shankdiameter=4|flutelength=22|length=50)\n",
            "(@FC|TOOL|number=2|name=Tapered|type=TaperedBallNose|diameter=2|shankdiameter=6|"
            "flutelength=15|length=50|taperangle=10)\n",
            "(@FC|TOOL|number=3|name=Bull|type=Bullnose|diameter=6|"
            "shankdiameter=6|cornerradius=1|flutelength=20|length=50)\n",
        ]
        table = parser.parse(lines)

        assert table[1].tool_type == ToolType.BALL_END_MILL
        assert table[2].tool_type == ToolType.TAPERED_MILL
        assert table[2].corner_radius == 1.0
        assert table[2].taper_angle_deg == 5.0
        assert table[3].tool_type == ToolType.BULL_NOSE_END_MILL
        assert table[3].corner_radius == 1.0

    def test_maps_shape_filename_stems(self, parser):
        lines = ["(@FC|TOOL|number=1|name=Thread|type=thread-mill|diameter=2)\n"]
        assert parser.parse(lines)[1].tool_type == ToolType.THREAD_MILL

    def test_unknown_type_falls_back_to_unknown(self, parser):
        lines = ["(@FC|TOOL|number=9|name=Mystery|type=Mystery Cutter|diameter=6)\n"]
        table = parser.parse(lines)

        assert table[9].tool_type == ToolType.UNKNOWN
        assert table[9].type_name == "Mystery Cutter"

    def test_ignores_duplicate_tool_entries(self, parser):
        lines = [
            "(@FC|TOOL|number=1|name=First|type=Endmill|diameter=6)\n",
            "(@FC|TOOL|number=1|name=Second|type=Ballend|diameter=8)\n",
        ]
        table = parser.parse(lines)

        assert table[1].diameter == 6.0
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_returns_empty_for_non_fc_header(self, parser):
        lines = ["(T1  Flat end mill  D=6 CR=0 - flat end mill)\n", "G0 X0\n"]
        assert parser.parse(lines) == {}

    def test_parses_semicolon_fc_comments(self, parser):
        lines = [";@FC|TOOL|number=5|name=Drill|type=Drill|diameter=3|tipangle=118\n"]
        tool = parser.parse(lines)[5]
        assert tool.tool_type == ToolType.DRILL
        assert tool.taper_angle_deg == 59.0


class TestToolDefinitionHelpers:
    def test_resolve_tool_type_normalises_names(self):
        assert resolve_tool_type("  Flat   End   Mill ", TOOL_TYPE_NAME_MAP) == ToolType.FLAT_END_MILL
        assert resolve_tool_type("", TOOL_TYPE_NAME_MAP) == ToolType.UNKNOWN
        assert resolve_tool_type("drill", TOOL_TYPE_NAME_MAP) == ToolType.DRILL
        assert resolve_tool_type("Flat End", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.FLAT_END_MILL
        assert resolve_tool_type("Engraving", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.ENGRAVING
        assert resolve_tool_type("Ball Nose", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.BALL_END_MILL
        assert resolve_tool_type("V-Bit", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.CHAMFER_MILL
        assert resolve_tool_type("Drill", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.DRILL
        assert resolve_tool_type("Tapered Ball Nose", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.TAPERED_MILL
        assert resolve_tool_type("Thread", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.THREAD_MILL
        assert resolve_tool_type("Bull Nose", MAKERA_STUDIO_TOOL_TYPE_NAME_MAP) == ToolType.BULL_NOSE_END_MILL
        assert resolve_tool_type("Endmill", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.FLAT_END_MILL
        assert resolve_tool_type("Ballend", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.BALL_END_MILL
        assert resolve_tool_type("VBit", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.CHAMFER_MILL
        assert resolve_tool_type("ThreadMill", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.THREAD_MILL
        assert resolve_tool_type("TaperedBallNose", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.TAPERED_MILL
        assert resolve_tool_type("thread-mill", FREECAD_MAKERA_TOOL_TYPE_NAME_MAP) == ToolType.THREAD_MILL

    def test_infer_shank_diameter(self):
        assert _infer_shank_diameter(ToolType.FLAT_END_MILL, 6.0) == 6.0
        assert _infer_shank_diameter(ToolType.RADIUS_MILL, 2.0, 2.0) == 6.0
        assert _infer_shank_diameter(ToolType.TAPERED_MILL, 1.5) is None
        assert _infer_shank_diameter(ToolType.LOLLIPOP_MILL, 6.0) is None
        assert _infer_shank_diameter(ToolType.CHAMFER_MILL, None) is None


class TestIconBuilder:
    def test_default_icon_for_missing_tool(self):
        assert get_tool_icon_path(None) == "data/GcodeViewer/tools/pointed_mill_thumb.png"

    def test_maps_known_tool_types(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.BALL_END_MILL)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/ball_end_mill_thumb.png"

    def test_maps_tapered_mill_icon(self):
        tool_def = ToolDefinition(number=12, tool_type=ToolType.TAPERED_MILL)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/tapered_mill_thumb.png"

    def test_maps_engraving_to_default_pointed_icon(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.ENGRAVING)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/pointed_mill_thumb.png"

    def test_maps_drill_to_default_pointed_icon(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.DRILL)
        assert get_tool_icon_path(tool_def) == "data/GcodeViewer/tools/pointed_mill_thumb.png"

    def test_tooltip_icons_use_full_body_assets(self):
        from carveracontroller.addons.tool_visualization.icon_builder import get_tool_tooltip_icon_path

        assert get_tool_tooltip_icon_path(None) == "data/GcodeViewer/tools/pointed_mill.png"
        tool_def = ToolDefinition(number=1, tool_type=ToolType.BALL_END_MILL)
        assert get_tool_tooltip_icon_path(tool_def) == "data/GcodeViewer/tools/ball_end_mill.png"


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

        assert tooltip == (
            "[size=17sp]T2 · Bull Nose End Mill[/size]\n"
            "[size=13sp]Roughing endmill[/size]\n"
            "[size=12sp][color=#8a8a8a]Makera[/color][/size]\n"
            "\n"
            "[color=#8a8a8a]Ø[/color] 6 mm"
            " [color=#8a8a8a]·[/color] "
            "[color=#8a8a8a]Corner radius[/color] 0.5 mm"
            " [color=#8a8a8a]·[/color] "
            "[color=#8a8a8a]Taper[/color] 5°"
        )

    def test_uses_enum_label_when_type_name_missing(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=3.0)
        assert format_tool_tooltip(tool_def) == (
            "[size=17sp]T1 · Flat End Mill[/size]\n\n[color=#8a8a8a]Ø[/color] 3 mm"
        )

    def test_prefers_enum_label_over_raw_type_name(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=6.0,
            type_name="flat end mill",
        )
        assert format_tool_tooltip(tool_def).startswith("[size=17sp]T1 · Flat End Mill[/size]")

    def test_falls_back_to_raw_type_name_for_unknown_type(self):
        tool_def = ToolDefinition(
            number=9,
            tool_type=ToolType.UNKNOWN,
            diameter=4.0,
            type_name="CNC HSS Slot Drill",
        )
        assert format_tool_tooltip(tool_def).startswith("[size=17sp]T9 · CNC HSS Slot Drill[/size]")

    def test_plain_text_without_markup(self):
        tool_def = ToolDefinition(
            number=2,
            tool_type=ToolType.BULL_NOSE_END_MILL,
            diameter=6.0,
            description="Roughing endmill",
            vendor="Makera",
            type_name="Bull nose end mill",
        )
        assert format_tool_tooltip(tool_def, markup=False) == (
            "T2 · Bull Nose End Mill\nRoughing endmill\nMakera\n\nØ 6 mm"
        )

    def test_appends_inch_unit_when_requested(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=0.25)
        assert "Ø 0.25 in" in format_tool_tooltip(tool_def, markup=False, unit="in")

    def test_escapes_markup_in_user_fields(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=3.0,
            description="Bit [special] & co",
            vendor="Acme [Tools]",
            type_name="flat end mill",
        )
        tooltip = format_tool_tooltip(tool_def)
        assert "Bit &bl;special&br; &amp; co" in tooltip
        assert "Acme &bl;Tools&br;" in tooltip
        assert "[special]" not in tooltip

    def test_includes_length_and_flute_when_present(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.ENGRAVING,
            diameter=3.175,
            shank_diameter=3.175,
            length=20.0,
            flute_length=12.0,
            type_name="Engraving",
        )
        tooltip = format_tool_tooltip(tool_def)

        assert "Ø[/color] 3.175 mm" in tooltip
        assert "Length[/color] 20 mm" in tooltip
        assert "Flute[/color] 12 mm" in tooltip
        assert "Engraving" in tooltip
        # Redundant shank matching diameter is omitted.
        assert "Shank" not in tooltip

    def test_hides_zero_corner_radius_and_shows_distinct_shank(self):
        tool_def = ToolDefinition(
            number=5,
            tool_type=ToolType.RADIUS_MILL,
            diameter=2.0,
            shank_diameter=6.0,
            corner_radius=0.0,
            type_name="Radius mill",
        )
        tooltip = format_tool_tooltip(tool_def)

        assert "Corner radius" not in tooltip
        assert "Shank[/color] 6 mm" in tooltip
        assert tooltip.startswith("[size=17sp]T5 · Radius Mill[/size]")

    def test_groups_thread_mill_dimensions(self):
        tool_def = ToolDefinition(
            number=4,
            tool_type=ToolType.THREAD_MILL,
            diameter=4.8,
            shank_diameter=6.0,
            length=50.0,
            flute_length=2.0,
            shoulder_length=20.0,
            thread_pitch=1.0,
            description="Makera_Carvera M6 Threadmill_Aluminum",
            type_name="thread mill",
        )
        tooltip = format_tool_tooltip(tool_def, markup=False)

        assert tooltip == (
            "T4 · Thread Mill\n"
            "Makera_Carvera M6 Threadmill_Aluminum\n"
            "\n"
            "Ø 4.8 mm · Shank 6 mm\n"
            "Length 50 mm · Flute 2 mm · Shoulder 20 mm\n"
            "Pitch 1 mm"
        )


class TestMeshBuilder:
    def test_build_tool_mesh_uses_expected_vertex_layout(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0)
        vertices, indices, fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        assert fmt == VERTEX_FORMAT
        assert len(vertices) % FLOATS_PER_VERTEX == 0
        assert len(indices) % 3 == 0
        assert all(0 <= index < vertex_count for index in indices)
        assert len(indices) > vertex_count

    def test_missing_stickout_uses_each_tools_own_diameter(self):
        tool_table = {
            1: ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=3.0),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=10.0),
        }
        meshes, _ = build_tool_meshes(tool_table, scale=1.0)

        assert _mesh_height(meshes[1][0]) == pytest.approx(3.0 * LENGTH_DIAMETER_FACTOR)
        assert _mesh_height(meshes[2][0]) == pytest.approx(10.0 * LENGTH_DIAMETER_FACTOR)

    def test_tiny_tool_gets_per_tool_visibility_floor(self):
        """Only the undersized tool is enlarged; a normal tool keeps true scale."""
        tool_table = {
            1: ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=0.01),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=1.0),
        }
        meshes, _ = build_tool_meshes(tool_table, scale=1.0)
        small_radius = _max_xy_radius(meshes[1][0])
        large_radius = _max_xy_radius(meshes[2][0])

        assert small_radius == pytest.approx(MIN_VISIBLE_RADIUS)
        assert large_radius == pytest.approx(0.5)

    def test_default_mesh_unaffected_by_tiny_tools(self):
        """Default mesh keeps fixed on-screen size when known tools need a floor."""
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

    def test_inch_tool_unit_scale_matches_mm_geometry(self):
        """Inch tool dims scaled by 25.4 should match equivalent mm dims at scale 1."""
        inch_tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=0.25, length=2.0)
        mm_tool = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.35, length=50.8)
        mesh_inch, _ = build_tool_meshes({1: inch_tool}, scale=unit_scale_to_mm("in"))
        mesh_mm, _ = build_tool_meshes({1: mm_tool}, scale=1.0)

        assert _mesh_height(mesh_inch[1][0]) == pytest.approx(_mesh_height(mesh_mm[1][0]))
        assert _max_xy_radius(mesh_inch[1][0]) == pytest.approx(_max_xy_radius(mesh_mm[1][0]))

    def test_flat_end_mill_side_normals_are_radial(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0)
        vertices, indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

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

        assert len(indices) > len(vertices) // FLOATS_PER_VERTEX

    def test_pointed_tip_mesh_shares_single_apex_vertex(self):
        tool_def = ToolDefinition(number=1, tool_type=ToolType.CHAMFER_MILL, diameter=6.0)
        vertices, _indices, _fmt = build_tool_mesh(tool_def)

        assert len(_apex_vertex_indices(vertices)) == 1

    def test_drill_uses_pointed_tip_with_default_taper_when_metadata_missing(self):
        # tip Ø == cutting Ø is treated as unset for drills (pointed tip).
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.DRILL,
            diameter=3.175,
            tip_diameter=3.175,
            length=12.0,
            flute_length=12.0,
        )
        profile = tool_profile(tool_def)

        assert profile[0] == pytest.approx((0.0, 0.0))
        # Default 118° point → 59° per side; cone height = r / tan(59°).
        expected_cone = (3.175 / 2.0) / math.tan(math.radians(59.0))
        assert profile[1][0] == pytest.approx(expected_cone)
        assert profile[1][1] == pytest.approx(3.175 / 2.0)

    @pytest.mark.parametrize(
        "tool_type",
        [
            ToolType.BULL_NOSE_END_MILL,
            ToolType.RADIUS_MILL,
            ToolType.CHAMFER_MILL,
            ToolType.TAPERED_MILL,
            ToolType.LOLLIPOP_MILL,
            ToolType.THREAD_MILL,
            ToolType.DRILL,
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
        flute_length = diameter * FALLBACK_FLUTE_DIAMETER_FACTOR
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
        # Missing flute → taper only through the capped flute region; shank stays cylindrical.
        end_radius = r_tan + (flute_length - z_tan) * math.tan(alpha)

        assert profile[0] == (0.0, pytest.approx(flat_radius))
        assert any(math.isclose(z, z_tan, abs_tol=1e-6) and math.isclose(r, r_tan, abs_tol=1e-6) for z, r in profile)
        assert profile[-1][0] == pytest.approx(shared_length)
        assert profile[-1][1] == pytest.approx(end_radius)
        assert profile[-1][1] > diameter / 2.0

    def test_tapered_mill_without_corner_radius_has_flat_tip(self):
        diameter = 6.0
        taper_angle_deg = 30.0
        shared_length = diameter * LENGTH_DIAMETER_FACTOR
        flute_length = diameter * FALLBACK_FLUTE_DIAMETER_FACTOR
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
        end_radius = tip_radius + flute_length * math.tan(math.radians(taper_angle_deg))
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

    def test_fusion_chamfer_taper_is_per_side_from_axis(self):
        """Fusion TAPER=45deg is 45° from the axis → 90° included tip."""
        diameter = 6.0
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.CHAMFER_MILL,
                diameter=diameter,
                tip_diameter=0.0,
                taper_angle_deg=45.0,
                flute_length=10.0,
                length=18.0,
            ),
            length=18.0,
        )
        assert profile[0] == (0.0, 0.0)
        assert profile[1] == (pytest.approx(diameter / 2.0), pytest.approx(diameter / 2.0))

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

    def test_explicit_length_and_flute_produce_shank_blend(self):
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.FLAT_END_MILL,
                diameter=2.0,
                shank_diameter=3.175,
                length=20.0,
                flute_length=12.0,
            )
        )
        flute_r = 1.0
        shank_r = 3.175 / 2.0
        transition = abs(shank_r - flute_r)  # ~45° blend

        assert profile[0] == (0.0, flute_r)
        assert (12.0, flute_r) in profile
        assert any(math.isclose(z, 12.0 + transition) and math.isclose(r, shank_r) for z, r in profile)
        assert profile[-1] == (20.0, pytest.approx(shank_r))
        # No hard radial step at the flute tip.
        assert not any(math.isclose(z, 12.0) and math.isclose(r, shank_r) for z, r in profile)

    def test_shoulder_keeps_cutting_diameter_before_shank_blend(self):
        """Makera: flute < shoulder < stick → body at D, then blend to handle."""
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.FLAT_END_MILL,
                diameter=2.0,
                shank_diameter=3.175,
                length=15.0,
                flute_length=6.0,
                shoulder_length=9.0,
            )
        )
        flute_r = 1.0
        shank_r = 3.175 / 2.0
        transition = abs(shank_r - flute_r)

        assert (6.0, flute_r) in profile
        assert (9.0, flute_r) in profile
        # Cutting diameter continues through the shoulder body (flute → shoulder).
        assert all(math.isclose(r, flute_r) for z, r in profile if z <= 9.0 + 1e-9)
        assert any(math.isclose(z, 9.0 + transition) and math.isclose(r, shank_r) for z, r in profile)
        assert profile[-1] == (15.0, pytest.approx(shank_r))
        assert not any(math.isclose(z, 9.0) and math.isclose(r, shank_r) for z, r in profile)

    def test_shoulder_equal_to_stick_has_no_handle_section(self):
        """Makera: shoulder == stick → 2mm body to the top, no 3.175 shank."""
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.FLAT_END_MILL,
                diameter=2.0,
                shank_diameter=3.175,
                length=12.0,
                flute_length=6.0,
                shoulder_length=12.0,
            )
        )
        flute_r = 1.0
        shank_r = 3.175 / 2.0

        assert profile[0] == (0.0, flute_r)
        assert (6.0, flute_r) in profile
        assert profile[-1] == (12.0, pytest.approx(flute_r))
        assert all(r <= flute_r + 1e-9 for _z, r in profile)
        assert not any(math.isclose(r, shank_r) for _z, r in profile)

    def test_mesh_uses_flute_color_without_flute_length(self):
        # Stick-out under the 4×D fallback flute cap → entire mesh is flute-colored.
        tool_def = ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0, length=18.0)
        vertices, _indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        for index in range(vertex_count):
            assert _vertex_color(vertices, index) == pytest.approx(FLUTE_COLOR)

    def test_missing_flute_capped_to_diameter_factor(self):
        diameter = 6.0
        length = 40.0
        flute_z = diameter * FALLBACK_FLUTE_DIAMETER_FACTOR
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=diameter,
            length=length,
        )
        vertices, _indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        colors = {_vertex_color(vertices, index) for index in range(vertex_count)}
        assert FLUTE_COLOR in colors
        assert SHANK_COLOR in colors
        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < flute_z - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > flute_z + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

        profile = tool_profile(tool_def)
        assert profile[-1][0] == pytest.approx(length)

    def test_mesh_colors_flute_and_shank_when_flute_length_available(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=2.0,
            shank_diameter=3.175,
            length=20.0,
            flute_length=12.0,
        )
        vertices, _indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        colors = {_vertex_color(vertices, index) for index in range(vertex_count)}
        assert FLUTE_COLOR in colors
        assert SHANK_COLOR in colors

        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < 12.0 - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > 12.0 + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

    def test_mesh_colors_flute_and_shoulder_when_no_handle_section(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.FLAT_END_MILL,
            diameter=2.0,
            shank_diameter=3.175,
            length=12.0,
            flute_length=6.0,
            shoulder_length=12.0,
        )
        vertices, _indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        colors = {_vertex_color(vertices, index) for index in range(vertex_count)}
        assert FLUTE_COLOR in colors
        assert SHANK_COLOR in colors

        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < 6.0 - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > 6.0 + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

    def test_infers_chamfer_flute_from_cone_when_metadata_missing(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.CHAMFER_MILL,
            diameter=6.0,
            # Fusion TAPER=45deg → 45° from axis → 90° included tip; cone height == radius.
            taper_angle_deg=45.0,
        )
        vertices, _indices, _fmt = build_tool_mesh(tool_def, length=18.0)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        colors = {_vertex_color(vertices, index) for index in range(vertex_count)}
        assert FLUTE_COLOR in colors
        assert SHANK_COLOR in colors
        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < 3.0 - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > 3.0 + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

    def test_inferred_flute_adds_short_shoulder_before_shank(self):
        """Fusion-like tip cue only: short body at D before the handle blend."""
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.CHAMFER_MILL,
                diameter=6.0,
                shank_diameter=8.0,
                taper_angle_deg=45.0,
                length=18.0,
            )
        )
        flute_z = 3.0
        cutting_r = 3.0
        shank_r = 4.0
        shoulder_z = flute_z + 6.0 * INFERRED_SHOULDER_DIAMETER_FACTOR
        transition = abs(shank_r - cutting_r)

        assert any(math.isclose(z, flute_z) and math.isclose(r, cutting_r) for z, r in profile)
        assert (shoulder_z, cutting_r) in profile
        # Shoulder body only — tip cone points below flute_z have r < cutting_r.
        assert all(math.isclose(r, cutting_r) for z, r in profile if flute_z - 1e-9 <= z <= shoulder_z + 1e-9)
        assert any(math.isclose(z, shoulder_z + transition) and math.isclose(r, shank_r) for z, r in profile)
        assert profile[-1] == (18.0, pytest.approx(shank_r))
        # Shank blend starts after the inferred shoulder, not at the tip.
        assert not any(math.isclose(z, flute_z) and math.isclose(r, shank_r) for z, r in profile)

    def test_infers_lollipop_flute_at_ball_neck_join(self):
        from carveracontroller.addons.tool_visualization.mesh_builder import _lollipop_ball_join_z

        diameter = 6.0
        ball_join = _lollipop_ball_join_z(diameter)
        tool_def = ToolDefinition(number=1, tool_type=ToolType.LOLLIPOP_MILL, diameter=diameter)
        vertices, _indices, _fmt = build_tool_mesh(tool_def, length=18.0)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        colors = {_vertex_color(vertices, index) for index in range(vertex_count)}
        assert FLUTE_COLOR in colors
        assert SHANK_COLOR in colors
        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < ball_join - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > ball_join + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

    def test_explicit_flute_length_not_overridden_by_inference(self):
        tool_def = ToolDefinition(
            number=1,
            tool_type=ToolType.CHAMFER_MILL,
            diameter=6.0,
            taper_angle_deg=45.0,
            length=20.0,
            flute_length=12.0,
        )
        vertices, _indices, _fmt = build_tool_mesh(tool_def)
        vertex_count = len(vertices) // FLOATS_PER_VERTEX

        for index in range(vertex_count):
            z = _vertex_z(vertices, index)
            color = _vertex_color(vertices, index)
            if z < 12.0 - 1e-6:
                assert color == pytest.approx(FLUTE_COLOR)
            elif z > 12.0 + 1e-6:
                assert color == pytest.approx(SHANK_COLOR)

    def test_missing_lengths_still_use_diameter_factor(self):
        profile = tool_profile(
            ToolDefinition(number=1, tool_type=ToolType.FLAT_END_MILL, diameter=6.0),
            length=None,
        )
        overall = 6.0 * LENGTH_DIAMETER_FACTOR
        flute_z = 6.0 * FALLBACK_FLUTE_DIAMETER_FACTOR
        assert profile[-1][0] == pytest.approx(overall)
        assert any(math.isclose(z, flute_z) for z, _r in profile)

    def test_engraving_tip_diameter_zero_is_pointed(self):
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.ENGRAVING,
                diameter=6.0,
                tip_diameter=0.0,
                taper_angle_deg=30.0,
            ),
            length=18.0,
        )
        assert profile[0] == (0.0, 0.0)

    def test_engraving_with_flat_tip(self):
        profile = tool_profile(
            ToolDefinition(
                number=1,
                tool_type=ToolType.ENGRAVING,
                diameter=6.0,
                tip_diameter=1.0,
                taper_angle_deg=30.0,
            ),
            length=18.0,
        )
        assert profile[0] == (0.0, 0.5)
        assert profile[0][1] > 0.0

    def test_build_tool_meshes_uses_per_tool_explicit_lengths(self):
        tool_table = {
            1: ToolDefinition(
                number=1,
                tool_type=ToolType.FLAT_END_MILL,
                diameter=2.0,
                length=12.0,
                flute_length=12.0,
            ),
            2: ToolDefinition(number=2, tool_type=ToolType.FLAT_END_MILL, diameter=10.0),
        }
        meshes, _ = build_tool_meshes(tool_table, scale=1.0)

        assert _mesh_height(meshes[1][0]) == pytest.approx(12.0)
        assert _mesh_height(meshes[2][0]) == pytest.approx(10.0 * LENGTH_DIAMETER_FACTOR)


class TestExtractor:
    def test_extract_tool_table_returns_first_non_empty_parser_result(self):
        lines = ["(T1  End mill  D=6 CR=0 - flat end mill)\n", "G0 X0\n"]
        table = extract_tool_table(lines)

        assert 1 in table
        assert table[1].tool_type == ToolType.FLAT_END_MILL

    def test_extract_tool_table_returns_empty_dict_when_unrecognised(self):
        lines = ["G0 X0 Y0\n", "G1 X1 F100\n"]
        assert extract_tool_table(lines) == {}

    def test_extract_prefers_makera_studio_when_mkr_header_present(self):
        lines = [
            ";@MKR|BEGIN\n",
            ";@MKR|TOOL|number=1|id=1|name=Flat|type=Flat End|handlediameter=3.175|"
            "sticklength=0|shoulderlength=12|flutelength=12|diameter=2|tipdiameter=2|"
            "cornerradius=0|angle=0|halfAngle=0\n",
            ";@MKR|END\n",
            "(T1  Should be ignored  D=99 CR=0 - flat end mill)\n",
            "G0 X0\n",
        ]
        table = extract_tool_table(lines)

        assert table[1].diameter == 2.0
        assert table[1].shank_diameter == 3.175
        assert table[1].product_id == "1"

    def test_extract_prefers_freecad_when_fc_header_present(self):
        lines = [
            "(Exported by FreeCAD)\n",
            "(@FC|TOOL|number=1|name=FreeCAD flat|type=Endmill|diameter=1.5|"
            "shankdiameter=3.175|flutelength=8|length=38)\n",
            "(T1  Should be ignored  D=99 CR=0 - flat end mill)\n",
            "G0 X0\n",
        ]
        table = extract_tool_table(lines)

        assert table[1].diameter == 1.5
        assert table[1].shank_diameter == 3.175
        assert table[1].description == "FreeCAD flat"
