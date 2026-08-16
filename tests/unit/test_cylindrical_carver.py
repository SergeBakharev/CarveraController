"""Unit tests for the cylindrical r(x, θ) stock carver."""

from __future__ import annotations

import numpy as np

from carveracontroller.addons.stock.simulator.carvers.cylindrical import CylindricalBackend
from carveracontroller.addons.stock.simulator.carvers.cylindrical.backend import (
    MAX_CYLINDRICAL_N_THETA,
    pick_cylindrical_dims,
    pose_ts_along_segment,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, rotate_yz
from carveracontroller.addons.stock.stock_shape import RotaryCylindricalStock
from carveracontroller.addons.tool_visualization.tool_definition import ToolDefinition, ToolType


def _flat_tool(diameter: float = 6.0, flute_length: float = 8.0) -> ToolDefinition:
    return ToolDefinition(
        number=1,
        tool_type=ToolType.FLAT_END_MILL,
        diameter=diameter,
        flute_length=flute_length,
        length=40.0,
    )


def test_cylindrical_seeds_full_radius():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 1.0, shape)
    assert cyl.hud_stats()["carver"] == "cylindrical"
    r = cyl.radius_at(20.0, 0.0)
    assert r is not None and abs(r - 14.0) < 1e-3


def test_indexed_a90_clears_side_not_top():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_pose_ts_point_is_single_sample():
    ts = pose_ts_along_segment((0, 0, 8), (0, 0, 8), 0.0, cell_size_mm=0.5, d_theta_deg=2.0)
    assert list(ts) == [0.0]


def test_pose_ts_constant_a_steps_along_xyz():
    ts = pose_ts_along_segment((0, 0, 8), (10, 0, 8), 0.0, cell_size_mm=0.5, d_theta_deg=2.0)
    assert len(ts) == 21
    assert ts[0] == 0.0 and ts[-1] == 1.0


def test_pose_ts_uses_the_finer_of_xyz_and_a():
    ts = pose_ts_along_segment((0, 0, 8), (10, 0, 8), 90.0, cell_size_mm=1.0, d_theta_deg=2.0)
    # XYZ → 11 samples; A → 46. A wins.
    assert len(ts) == 46


def test_indexed_a90_feed_clears_along_x():
    """Constant-A X feeds must sweep the whole segment, not only p0."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((8.0, 0.0, 8.0), (32.0, 0.0, 8.0), tool, a0=90.0, a1=90.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(8.0, y, z)
    assert not cyl.is_solid_at_world(20.0, y, z)
    assert not cyl.is_solid_at_world(32.0, y, z)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_wrapping_shallow_helix_clears_mid_x():
    """Small ΔA over a long X move must still sample along XYZ."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((6.0, 0.0, 8.0), (34.0, 0.0, 8.0), tool, a0=0.0, a1=4.0)
    assert not cyl.is_solid_at_world(6.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(34.0, 0.0, 10.0)


def test_wrapping_a_clears_arc():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=90.0)
    assert dirty
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    y, z = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(20.0, y, z)


def test_wrapping_helix_clears_along_x():
    """ΔA-dominated helix should sample poses, not only the endpoints."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((8.0, 0.0, 8.0), (16.0, 0.0, 8.0), tool, a0=0.0, a1=90.0)
    assert not cyl.is_solid_at_world(8.0, 0.0, 10.0)
    y90, z90 = rotate_yz(0.0, 10.0, 90.0)
    assert not cyl.is_solid_at_world(16.0, y90, z90)
    y45, z45 = rotate_yz(0.0, 10.0, 45.0)
    assert not cyl.is_solid_at_world(12.0, y45, z45)
    assert cyl.is_solid_at_world(16.0, 0.0, 10.0)


def test_cylindrical_mesh_tiles():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    assert list(meshes) == [(0, 0, 0)]
    assert any(v is not None for v in meshes.values())


def test_cylindrical_mesh_is_regular_grid():
    """One quad per (x, θ) cell so sloped features don't open T-junction holes."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=32, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=32.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4


def test_cylindrical_sloped_mesh_stays_regular():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    xs = np.linspace(0.0, 1.0, cyl.nx, dtype=np.float32)[:, None]
    th = np.linspace(0.0, 1.0, cyl.n_theta, dtype=np.float32)[None, :]
    cyl.radii[:, :] = 6.0 + 3.0 * xs + 2.0 * th
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    n_verts = sum(len(m[0]) // 12 for m in meshes.values() if m)
    n_quads = (cyl.nx - 1) * cyl.n_theta + 2 * cyl.n_theta
    assert n_verts == n_quads * 4


def test_cylindrical_slope_triangles_face_outward():
    """Back-face culling hides any triangle whose geometric normal points inward."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    xs = np.linspace(0.0, 1.0, cyl.nx, dtype=np.float32)[:, None]
    th = np.linspace(0.0, 1.0, cyl.n_theta, dtype=np.float32)[None, :]
    cyl.radii[:, :] = 6.0 + 3.0 * xs + 2.0 * th
    meshes = cyl.mesh_tiles(cyl.initial_surface_keys())
    flipped = 0
    checked = 0
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        idx = np.asarray(packed[1], dtype=np.int32)
        pos = verts[:, :3]
        for i in range(0, idx.size, 3):
            a, b, c = pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]
            n = np.cross(b - a, c - a)
            if np.linalg.norm(n) < 1e-10:
                continue
            # End caps are constant-X; skip them (normal is ±X, not radial).
            if abs(a[0] - b[0]) < 1e-4 and abs(a[0] - c[0]) < 1e-4:
                continue
            mid = (a + b + c) / 3.0
            hint = np.array((0.0, mid[1] - cyl.axis_y, mid[2] - cyl.axis_z), dtype=np.float64)
            checked += 1
            if float(np.dot(n, hint)) <= 0.0:
                flipped += 1
    assert checked > 0
    assert flipped == 0


def _mesh_normals(meshes: dict) -> np.ndarray:
    rows = []
    for packed in meshes.values():
        if not packed:
            continue
        verts = np.asarray(packed[0], dtype=np.float32).reshape(-1, 12)
        rows.append(verts[:, 3:6])
    assert rows
    return np.concatenate(rows, axis=0)


def test_cylindrical_flat_cut_sets_radius_to_tip():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=0.0)
    r = cyl.radius_at(20.0, 0.0)
    assert r is not None
    assert abs(r - 8.0) < 0.6
    assert cyl.is_solid_at_world(20.0, 0.0, 7.5)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_cylindrical_ball_mill_clears_top():
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = ToolDefinition(
        number=1,
        tool_type=ToolType.BALL_END_MILL,
        diameter=6.0,
        flute_length=8.0,
        length=40.0,
    )
    dirty = cyl.carve_segment((20.0, 0.0, 8.0), (20.0, 0.0, 8.0), tool, a0=0.0, a1=0.0)
    assert dirty
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert cyl.is_solid_at_world(20.0, 0.0, 7.0)


def test_cylindrical_mesh_has_end_caps():
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=20, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=20.0)
    cyl = CylindricalBackend(bounds, 2.0, shape)
    nrm = _mesh_normals(cyl.mesh_tiles(cyl.initial_surface_keys()))
    assert np.any(nrm[:, 0] < -0.5)
    assert np.any(nrm[:, 0] > 0.5)


def test_cylindrical_y_offset_clears_side():
    """Indexed A=0 with Y ≠ 0 must center the θ window on the tool azimuth."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 8.0, 10.0), (20.0, 8.0, 10.0), tool, a0=0.0, a1=0.0)
    assert not cyl.is_solid_at_world(20.0, 8.0, 11.0)
    assert cyl.is_solid_at_world(20.0, 0.0, 10.0)


def test_cylindrical_theta_pad_uses_tangent_half_angle():
    """θ pad must be asin(R/D); atan(R/D) misses surface hits on a Y-offset mill."""
    bounds = StockBounds(min_x=0, min_y=-10, min_z=-10, max_x=40, max_y=10, max_z=10)
    shape = RotaryCylindricalStock(diameter_mm=20.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=10.0)
    cyl.carve_segment((20.0, 4.0, 1.0), (20.0, 4.0, 1.0), tool, a0=0.0, a1=0.0)
    # Surface point at θ≈17°. Tool azimuth is ~76°; atan(reach/D)+dθ ≈ 43°
    # does not cover it, asin (tangent) ≈ 61° does.
    assert not cyl.is_solid_at_world(20.0, 2.8, 9.1)
    assert cyl.is_solid_at_world(20.0, 0.0, -9.0)


def test_cylindrical_plunge_clears_far_theta():
    """A plunge that overlaps the A-axis must not drop the far θ half."""
    bounds = StockBounds(min_x=0, min_y=-14, min_z=-14, max_x=40, max_y=14, max_z=14)
    shape = RotaryCylindricalStock(diameter_mm=28.0, length_mm=40.0)
    cyl = CylindricalBackend(bounds, 0.5, shape)
    tool = _flat_tool(diameter=6.0, flute_length=8.0)
    cyl.carve_segment((20.0, 0.0, 14.0), (20.0, 0.0, -14.0), tool, a0=0.0, a1=0.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, 10.0)
    assert not cyl.is_solid_at_world(20.0, 0.0, -10.0)


def test_pick_cylindrical_dims_caps_n_theta_on_puck():
    """A tiny cell_size on a short Ø80 puck must not explode θ samples."""
    bounds = StockBounds(0, -40, -40, 5, 40, 40)
    nx, n_theta, d_theta = pick_cylindrical_dims(bounds, 0.01, 80.0)
    assert nx == 500
    assert n_theta == MAX_CYLINDRICAL_N_THETA
    assert n_theta % 4 == 0
    assert n_theta * d_theta == 360.0
