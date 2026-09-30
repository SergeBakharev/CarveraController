"""Voxel carver backend wrapping the existing chunked occupancy grid."""

from __future__ import annotations

import math

import numpy as np

from carveracontroller.addons.stock.simulator.carver_select import resolve_cutting_profile
from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, CarverBackend, TileKey
from carveracontroller.addons.stock.simulator.carvers.laser_map import (
    LaserDecalMixin,
    LaserMap,
    laser_burn_uint8,
    pick_laser_cell_size_mm,
    split_laser_snapshot,
    stroke_parts,
    stroke_radius_mm,
)
from carveracontroller.addons.stock.stock_geometry import StockBounds, stock_theta_deg
from carveracontroller.addons.stock.stock_shape import RectangularStock, StockShape

from .checkpoints import CheckpointStore, restore_voxel_checkpoint
from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid
from .mesher import mesh_dirty_chunks
from .occupancy import expand_dirty_with_neighbors, exterior_chunk_keys, non_full_chunk_keys, seed_shape_occupancy


class VoxelBackend(LaserDecalMixin):
    """3D voxel occupancy — accurate for undercuts and arbitrary kinematics."""

    kind = "voxel"

    def __init__(
        self,
        bounds: StockBounds,
        cell_size_mm: float,
        shape: StockShape | None = None,
        chunk_size: int = DEFAULT_TILE_SIZE,
        *,
        grid: ChunkedVoxelGrid | None = None,
        seed: bool = True,
        has_4axis: bool = False,
        laser_cell_size_mm: float | None = None,
    ):
        self.bounds = bounds
        self.cell_size = float(cell_size_mm)
        self.chunk_size = int(chunk_size)
        self.shape: StockShape = shape or RectangularStock(
            width_mm=max(bounds.size[0], 1e-6),
            length_mm=max(bounds.size[1], 1e-6),
            height_mm=max(bounds.size[2], 1e-6),
        )
        self.has_4axis = bool(has_4axis)
        self._laser_cell_size = (
            float(laser_cell_size_mm)
            if laser_cell_size_mm is not None
            else pick_laser_cell_size_mm(bounds, self.cell_size, cylindrical=self.has_4axis)
        )
        self.grid = grid if grid is not None else ChunkedVoxelGrid(bounds, cell_size_mm, chunk_size)
        if seed and grid is None:
            seed_shape_occupancy(self.grid, self.shape)
        self._init_laser()

    @property
    def voxel_size(self) -> float:
        return self.cell_size

    def reset_occupancy(self) -> set[TileKey]:
        self.grid.reset()
        seed_shape_occupancy(self.grid, self.shape)
        self._drop_laser()
        return self.initial_surface_keys()

    def clone_empty(self) -> VoxelBackend:
        return VoxelBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.chunk_size,
            seed=True,
            has_4axis=self.has_4axis,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def _make_laser_map(self) -> LaserMap:
        if self.has_4axis:
            from carveracontroller.addons.stock.simulator.carvers.cylindrical.backend import pick_cylindrical_dims

            diameter = min(self.bounds.size[1], self.bounds.size[2])
            nx, n_theta, d_theta = pick_cylindrical_dims(self.bounds, self._laser_cell_size, diameter)
            return LaserMap.cylindrical(self.bounds, nx, n_theta, self._laser_cell_size, d_theta)
        from carveracontroller.addons.stock.simulator.carvers.heightmap.backend import pick_heightmap_size

        nx, ny = pick_heightmap_size(self.bounds, self._laser_cell_size)
        return LaserMap.planar(self.bounds, nx, ny, self._laser_cell_size)

    def carve_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
        profile=None,
    ) -> set[TileKey]:
        if profile is None:
            profile = resolve_cutting_profile(tool_def, tool_unit_scale=tool_unit_scale)
        return self.carve_segments([(p0, p1, a0, a1)], profile, tool_unit_scale=tool_unit_scale, tool_def=tool_def)

    def carve_segments(
        self,
        segments,
        profile,
        tool_unit_scale: float = 1.0,
        tool_def=None,
    ) -> set[TileKey]:
        del tool_unit_scale, tool_def
        if not segments or not profile:
            return set()
        from carveracontroller.addons.stock.simulator.native import carve_voxels

        dirty = carve_voxels(self.grid, list(segments), profile)
        if self._laser is not None:
            max_r = max((r for _z, r in profile), default=0.0)
            if max_r > 0 and self._clear_laser_batch(segments, max_r):
                self._laser_dirty = True
        return dirty

    def _clear_laser_batch(self, segments, radius: float) -> bool:
        laser = self._laser
        if laser is None or not segments:
            return False
        from carveracontroller.addons.stock.simulator.native import clear_laser_capsules

        u0: list[float] = []
        v0: list[float] = []
        u1: list[float] = []
        v1: list[float] = []
        cylindrical = laser.mode == "cylindrical"
        for p0, p1, a0, a1 in segments:
            if cylindrical:
                u0.append(float(p0[0]))
                v0.append(self._stock_theta(p0, a0))
                u1.append(float(p1[0]))
                v1.append(self._stock_theta(p1, a1))
            else:
                u0.append(float(p0[0]))
                v0.append(float(p0[1]))
                u1.append(float(p1[0]))
                v1.append(float(p1[1]))
        return clear_laser_capsules(
            laser.intensity,
            u0,
            v0,
            u1,
            v1,
            float(radius),
            cell_u=laser.cell_u,
            cell_v=laser.cell_v,
            origin_u=laser.origin_u,
            origin_v=laser.origin_v,
            wrap_v=laser.wrap_v,
            v_period=laser.v_period,
            v_scale=laser.v_scale,
            dirty=laser.dirty_native_args(),
        )

    def _axis_yz(self) -> tuple[float, float]:
        return (
            0.5 * (self.bounds.min_y + self.bounds.max_y),
            0.5 * (self.bounds.min_z + self.bounds.max_z),
        )

    def _stock_theta(self, p: tuple[float, float, float], angle_deg: float) -> float:
        ay, az = self._axis_yz()
        return stock_theta_deg(p[1], p[2], angle_deg, ay, az)

    def engrave_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def=None,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
        power_s: float | None = None,
    ) -> bool:
        del tool_def, tool_unit_scale
        burn = laser_burn_uint8(power_s)
        if not burn:
            return False
        radius = stroke_radius_mm(self._laser_cell_size)
        laser = self._ensure_laser()
        allow, origin = self._laser_allow_mask(laser, p0, p1, a0, a1, radius)
        if laser.mode == "cylindrical":
            changed = laser.paint_segment(
                p0[0],
                self._stock_theta(p0, a0),
                p1[0],
                self._stock_theta(p1, a1),
                radius,
                allow,
                allow_origin=origin,
                burn=burn,
            )
        else:
            changed = laser.paint_segment(
                p0[0],
                p0[1],
                p1[0],
                p1[1],
                radius,
                allow,
                allow_origin=origin,
                burn=burn,
            )
        if changed:
            self._laser_dirty = True
        elif self._laser is not None and not np.any(self._laser.intensity):
            self._drop_laser()
        return changed

    def engrave_segments(self, jobs, tool_unit_scale: float = 1.0) -> bool:
        changed = False
        for item in jobs:
            p0, p1, a0, a1, power = stroke_parts(item)
            if self.engrave_segment(p0, p1, None, tool_unit_scale, a0=a0, a1=a1, power_s=power):
                changed = True
        return changed

    def _sample_solid_world(self, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> np.ndarray:
        """Vectorized occupancy sample matching ``ChunkedVoxelGrid.is_solid_at_world``."""
        out = np.zeros(xs.shape, dtype=bool)
        b = self.bounds
        valid = (
            (b.min_x <= xs)
            & (xs < b.max_x)
            & (b.min_y <= ys)
            & (ys < b.max_y)
            & (b.min_z <= zs)
            & (zs < b.max_z)
        )
        if not np.any(valid):
            return out
        vox = max(float(self.cell_size), 1e-12)
        ix = np.floor((xs - b.min_x) / vox).astype(np.int32)
        iy = np.floor((ys - b.min_y) / vox).astype(np.int32)
        iz = np.floor((zs - b.min_z) / vox).astype(np.int32)
        in_grid = valid & (ix >= 0) & (ix < self.grid.nx) & (iy >= 0) & (iy < self.grid.ny) & (iz >= 0) & (iz < self.grid.nz)
        if not np.any(in_grid):
            return out
        cs = int(self.grid.chunk_size)
        cx = ix // cs
        cy = iy // cs
        cz = iz // cs
        # Flatten chunk ids for grouping; stroke windows almost always hit one chunk.
        chunk_id = (cx.astype(np.int64) * 1_000_003 + cy.astype(np.int64)) * 1_000_003 + cz.astype(np.int64)
        flat = np.flatnonzero(in_grid)
        ids = chunk_id.ravel()[flat]
        order = np.argsort(ids, kind="mergesort")
        flat = flat[order]
        ids = ids[order]
        starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
        ends = np.r_[starts[1:], ids.size]
        for s, e in zip(starts.tolist(), ends.tolist()):
            idx = flat[s:e]
            i0 = int(ix.ravel()[idx[0]])
            j0 = int(iy.ravel()[idx[0]])
            k0 = int(iz.ravel()[idx[0]])
            coord = self.grid.chunk_of_voxel(i0, j0, k0)
            state = self.grid.get_chunk_state(coord)
            if state is CHUNK_FULL:
                out.ravel()[idx] = True
                continue
            if state is CHUNK_EMPTY:
                continue
            lx = ix.ravel()[idx] - coord.cx * cs
            ly = iy.ravel()[idx] - coord.cy * cs
            lz = iz.ravel()[idx] - coord.cz * cs
            out.ravel()[idx] = state[lx, ly, lz].astype(bool, copy=False)  # type: ignore[index]
        return out

    def _stock_under_laser_xy(self, x: float, y: float, z_laser: float) -> bool:
        """True if remaining stock sits at/just under the beam (top plane is exclusive max_z)."""
        b = self.bounds
        if not (b.min_x <= x < b.max_x and b.min_y <= y < b.max_y):
            return False
        z_hi = min(float(z_laser), b.max_z - 1e-6)
        z_hi = max(z_hi, b.min_z)
        if self.grid.is_solid_at_world(x, y, z_hi):
            return True
        z_in = max(z_hi - 0.51 * self.cell_size, b.min_z + 1e-6)
        return self.grid.is_solid_at_world(x, y, z_in)

    def _stock_under_laser_xy_grid(self, x: np.ndarray, y: np.ndarray, z_laser: float) -> np.ndarray:
        """Vectorized planar stock test for a laser allow window."""
        b = self.bounds
        allow = np.zeros(x.shape, dtype=np.uint8)
        in_xy = (b.min_x <= x) & (x < b.max_x) & (b.min_y <= y) & (y < b.max_y)
        if not np.any(in_xy):
            return allow
        z_hi = min(float(z_laser), b.max_z - 1e-6)
        z_hi = max(z_hi, b.min_z)
        z_hi_a = np.full(x.shape, z_hi, dtype=np.float64)
        solid = self._sample_solid_world(x, y, z_hi_a)
        z_in = max(z_hi - 0.51 * self.cell_size, b.min_z + 1e-6)
        if z_in < z_hi - 1e-12:
            need = in_xy & ~solid
            if np.any(need):
                solid = solid | self._sample_solid_world(x, y, np.full(x.shape, z_in, dtype=np.float64))
        allow[in_xy & solid] = 1
        return allow

    def _laser_allow_mask(
        self,
        laser: LaserMap,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        a0: float,
        a1: float,
        radius: float,
    ) -> tuple[np.ndarray, tuple[int, int]]:
        """Uint8 allow window whose [0,0] is laser index (iu0, iv0)."""
        z_mid = 0.5 * (p0[2] + p1[2])
        axis_y, axis_z = self._axis_yz()
        pad = radius + laser.cell_u
        iu0 = max(0, int(math.floor((min(p0[0], p1[0]) - pad - laser.origin_u) / laser.cell_u)))
        iu1 = min(laser.nx - 1, int(math.floor((max(p0[0], p1[0]) + pad - laser.origin_u) / laser.cell_u)))
        if iu0 > iu1:
            return np.zeros((0, 0), dtype=np.uint8), (0, 0)
        probe_r = min(
            0.5 * min(self.bounds.size[1], self.bounds.size[2]),
            math.hypot(p0[1] - axis_y, p0[2] - axis_z),
        )
        probe_r = max(0.0, probe_r - 0.51 * self.cell_size)
        rows = iu1 - iu0 + 1
        uu = laser.origin_u + (np.arange(iu0, iu1 + 1, dtype=np.float64) + 0.5) * laser.cell_u
        if laser.wrap_v:
            pad_v = radius / max(laser.v_scale, 1e-12) + laser.cell_v
            iv_idx = laser._wrapped_v_indices(
                self._stock_theta(p0, a0),
                self._stock_theta(p1, a1),
                pad_v,
            )
            # Contiguous window in laser index space; wrap spans use the full θ ring.
            iv_unique = np.unique(iv_idx.astype(np.int32) % laser.nv)
            if iv_unique.size == 0:
                return np.zeros((rows, 0), dtype=np.uint8), (iu0, 0)
            iv0 = int(iv_unique.min())
            iv1 = int(iv_unique.max())
            if iv1 - iv0 + 1 == int(iv_unique.size):
                cols = iv1 - iv0 + 1
                ivs = np.arange(iv0, iv1 + 1, dtype=np.int32)
            else:
                iv0 = 0
                cols = laser.nv
                ivs = np.arange(laser.nv, dtype=np.int32)
            allow = np.zeros((rows, cols), dtype=np.uint8)
            selected = np.zeros(laser.nv, dtype=bool)
            selected[iv_unique] = True
            use = selected[ivs]
            if not np.any(use):
                return allow, (iu0, iv0)
            ang = np.radians((ivs.astype(np.float64) + 0.5) * laser.cell_v)
            ys = axis_y + np.sin(ang) * probe_r
            zs = axis_z + np.cos(ang) * probe_r
            X = np.broadcast_to(uu[:, None], (rows, cols))
            Y = np.broadcast_to(ys[None, :], (rows, cols))
            Z = np.broadcast_to(zs[None, :], (rows, cols))
            solid = self._sample_solid_world(X, Y, Z)
            allow[:, use] = solid[:, use].astype(np.uint8, copy=False)
            return np.ascontiguousarray(allow), (iu0, iv0)

        iv0 = max(0, int(math.floor((min(p0[1], p1[1]) - pad - laser.origin_v) / laser.cell_v)))
        iv1 = min(laser.nv - 1, int(math.floor((max(p0[1], p1[1]) + pad - laser.origin_v) / laser.cell_v)))
        if iv0 > iv1:
            return np.zeros((rows, 0), dtype=np.uint8), (iu0, 0)
        vv = laser.origin_v + (np.arange(iv0, iv1 + 1, dtype=np.float64) + 0.5) * laser.cell_v
        X, Y = np.meshgrid(uu, vv, indexing="ij")
        allow = self._stock_under_laser_xy_grid(X, Y, z_mid)
        return np.ascontiguousarray(allow), (iu0, iv0)

    def snapshot_full(self) -> object:
        raw, _nbytes = self.grid.snapshot_non_full()
        return self._snapshot_with_laser(("full", raw), full=True)

    def snapshot_changed(self, keys: set[TileKey]) -> object:
        delta: dict[TileKey, object] = {}
        for key in keys:
            state = self.grid.get_chunk_state(ChunkCoord(*key))
            if state is CHUNK_FULL:
                delta[key] = CHUNK_FULL
            elif state is CHUNK_EMPTY:
                delta[key] = CHUNK_EMPTY
            elif isinstance(state, object) and hasattr(state, "copy"):
                delta[key] = state.copy()
            else:
                delta[key] = state
        return self._snapshot_with_laser(("delta", delta), full=False)

    def restore(self, payload: object) -> set[TileKey]:
        occ, laser_payload = split_laser_snapshot(payload)
        kind, data = occ  # type: ignore[misc]
        if kind == "full":
            self.grid.restore_non_full(data)
            self._restore_laser_payload(laser_payload, occupancy_kind=kind)
            return set(data.keys()) | self.initial_surface_keys()
        for key, state in data.items():
            if state is CHUNK_FULL:
                self.grid._chunks.pop(key, None)
            elif state is CHUNK_EMPTY:
                self.grid._chunks[key] = CHUNK_EMPTY
            else:
                self.grid._chunks[key] = state.copy() if hasattr(state, "copy") else state
        self._restore_laser_payload(laser_payload, occupancy_kind=kind)
        return set(data.keys())

    def copy_tiles(self, keys: set[TileKey]) -> VoxelBackend:
        copied = self.grid.copy_chunks(keys)
        return VoxelBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.chunk_size,
            grid=copied,
            seed=False,
            has_4axis=self.has_4axis,
            laser_cell_size_mm=self._laser_cell_size,
        )

    def mesh_tiles(self, keys: set[TileKey]) -> dict[TileKey, tuple | None]:
        return mesh_dirty_chunks(self.grid, keys)

    def expand_dirty(self, dirty: set[TileKey]) -> set[TileKey]:
        return expand_dirty_with_neighbors(self.grid, dirty)

    def initial_surface_keys(self) -> set[TileKey]:
        dirty = exterior_chunk_keys(self.grid)
        dirty.update(non_full_chunk_keys(self.grid))
        return dirty

    def all_non_full_keys(self) -> set[TileKey]:
        return non_full_chunk_keys(self.grid)

    def hud_stats(self) -> dict:
        g = self.grid
        return {
            "carver": self.kind,
            "cell_size_mm": float(g.voxel_size),
            "grid_nx": int(g.nx),
            "grid_ny": int(g.ny),
            "grid_nz": int(g.nz),
        }

    @staticmethod
    def create_checkpoint_store(slot_count: int):
        """Voxel bit-packed chunk checkpoints (defined next to the grid carver)."""
        return CheckpointStore(slot_count=slot_count)

    @staticmethod
    def restore_checkpoint(store, checkpoint, backend) -> set:
        return restore_voxel_checkpoint(backend, store, checkpoint)


# Satisfy the protocol for type checkers.
_: type[CarverBackend] = VoxelBackend  # type: ignore[misc,assignment]
