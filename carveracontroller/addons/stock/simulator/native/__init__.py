"""Native stock carving. Cut simulation is unavailable when the extension is absent."""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np

HAS_NATIVE = False
_impl = None

try:
    from .lib import _stock_carve as _impl

    HAS_NATIVE = True
except ImportError:
    try:
        # iOS links a static module; Android installs the extension in site-packages.
        import _stock_carve as _impl

        HAS_NATIVE = True
    except ImportError:
        _impl = None


def native_enabled() -> bool:
    return _impl is not None


def _require_impl():
    if _impl is None:
        raise RuntimeError("native stock carve extension is not built")
    return _impl


def pack_profile(profile: Iterable[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    rows = list(profile)
    if not rows:
        return np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64)
    zs = np.ascontiguousarray([z for z, _r in rows], dtype=np.float64)
    rs = np.ascontiguousarray([r for _z, r in rows], dtype=np.float64)
    return zs, rs


def _soa(segments: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(segments)
    p0 = np.empty((n, 3), dtype=np.float64)
    p1 = np.empty((n, 3), dtype=np.float64)
    a0 = np.empty(n, dtype=np.float64)
    a1 = np.empty(n, dtype=np.float64)
    for i, seg in enumerate(segments):
        p0[i, :] = seg[0]
        p1[i, :] = seg[1]
        a0[i] = float(seg[2]) if len(seg) > 2 else 0.0
        a1[i] = float(seg[3]) if len(seg) > 3 else a0[i]
    return p0, p1, a0, a1


def _laser_call_args(
    image: np.ndarray | None,
    *,
    cell_u: float,
    cell_v: float,
    origin_u: float,
    origin_v: float,
    wrap_v: bool,
    v_period: float,
    flag: np.ndarray,
) -> tuple:
    if image is None:
        return (None, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, flag)
    return (
        image,
        int(image.shape[0]),
        int(image.shape[1]),
        float(cell_u),
        float(cell_v),
        float(origin_u),
        float(origin_v),
        1 if wrap_v else 0,
        float(v_period),
        flag,
    )


def carve_heightmap(
    heights: np.ndarray,
    *,
    min_x: float,
    min_y: float,
    min_z: float,
    cell: float,
    tile: int,
    segments: list,
    profile: list[tuple[float, float]],
    hit_mask: np.ndarray | None = None,
    laser: np.ndarray | None = None,
    laser_cell_u: float = 0.0,
    laser_cell_v: float = 0.0,
    laser_origin_u: float = 0.0,
    laser_origin_v: float = 0.0,
) -> tuple[set[tuple[int, int, int]], bool]:
    if not segments or not profile:
        return set(), False
    impl = _require_impl()
    nx, ny = int(heights.shape[0]), int(heights.shape[1])
    ntx = max(1, int(math.ceil(nx / max(int(tile), 1))))
    nty = max(1, int(math.ceil(ny / max(int(tile), 1))))
    tiles = np.zeros(ntx * nty, dtype=np.uint8)
    p0, p1, _a0, _a1 = _soa(segments)
    zs, rs = pack_profile(profile)
    heights_c = np.ascontiguousarray(heights)
    laser_c = np.ascontiguousarray(laser) if laser is not None else None
    flag = np.zeros(1, dtype=np.uint8)
    dirty = impl.heightmap(
        heights_c,
        nx,
        ny,
        int(tile),
        float(min_x),
        float(min_y),
        float(min_z),
        float(cell),
        len(segments),
        p0,
        p1,
        zs,
        rs,
        ntx,
        nty,
        hit_mask if hit_mask is not None else None,
        tiles,
        *_laser_call_args(
            laser_c,
            cell_u=laser_cell_u,
            cell_v=laser_cell_v,
            origin_u=laser_origin_u,
            origin_v=laser_origin_v,
            wrap_v=False,
            v_period=0.0,
            flag=flag,
        ),
    )
    if heights_c is not heights:
        heights[...] = heights_c
    if laser_c is not None and laser is not None and laser_c is not laser:
        laser[...] = laser_c
    return set(dirty), bool(flag[0])


def carve_cylindrical(
    radii: np.ndarray,
    *,
    min_x: float,
    cell: float,
    d_theta: float,
    axis_y: float,
    axis_z: float,
    stock_radius: float,
    sin_t: np.ndarray,
    cos_t: np.ndarray,
    tile: int,
    segments: list,
    profile: list[tuple[float, float]],
    changed_mask: np.ndarray | None = None,
    laser: np.ndarray | None = None,
    laser_cell_u: float = 0.0,
    laser_cell_v: float = 0.0,
    laser_origin_u: float = 0.0,
    laser_origin_v: float = 0.0,
    laser_wrap: bool = False,
    laser_period: float = 360.0,
) -> tuple[set[tuple[int, int, int]], bool]:
    if not segments or not profile:
        return set(), False
    impl = _require_impl()
    nx, n_theta = int(radii.shape[0]), int(radii.shape[1])
    ntx = max(1, int(math.ceil(nx / max(int(tile), 1))))
    ntt = max(1, int(math.ceil(n_theta / max(int(tile), 1))))
    tiles = np.zeros(ntx * ntt, dtype=np.uint8)
    p0, p1, a0, a1 = _soa(segments)
    zs, rs = pack_profile(profile)
    radii_c = np.ascontiguousarray(radii)
    laser_c = np.ascontiguousarray(laser) if laser is not None else None
    flag = np.zeros(1, dtype=np.uint8)
    dirty = impl.cylindrical(
        radii_c,
        nx,
        n_theta,
        int(tile),
        float(min_x),
        float(cell),
        float(d_theta),
        float(axis_y),
        float(axis_z),
        float(stock_radius),
        np.ascontiguousarray(sin_t, dtype=np.float64),
        np.ascontiguousarray(cos_t, dtype=np.float64),
        len(segments),
        p0,
        p1,
        a0,
        a1,
        zs,
        rs,
        ntx,
        ntt,
        changed_mask if changed_mask is not None else None,
        tiles,
        *_laser_call_args(
            laser_c,
            cell_u=laser_cell_u,
            cell_v=laser_cell_v,
            origin_u=laser_origin_u,
            origin_v=laser_origin_v,
            wrap_v=laser_wrap,
            v_period=laser_period,
            flag=flag,
        ),
    )
    if radii_c is not radii:
        radii[...] = radii_c
    if laser_c is not None and laser is not None and laser_c is not laser:
        laser[...] = laser_c
    return set(dirty), bool(flag[0])


def carve_voxels(grid, segments: list, profile: list[tuple[float, float]]) -> set[tuple[int, int, int]]:
    """Carve ``segments`` into ``grid``. Materialise happens in the callback."""
    if not segments or not profile:
        return set()
    impl = _require_impl()
    from carveracontroller.addons.stock.simulator.carvers.voxel.grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord

    p0, p1, a0, a1 = _soa(segments)
    zs, rs = pack_profile(profile)

    def get_chunk(cx: int, cy: int, cz: int):
        coord = ChunkCoord(int(cx), int(cy), int(cz))
        state = grid.get_chunk_state(coord)
        if state is CHUNK_EMPTY:
            return None
        was_full = state is CHUNK_FULL or (coord.as_tuple() not in grid._chunks)
        arr = grid.get_or_create_chunk(coord)
        if arr is None:
            return None
        if was_full:
            # Materialise path already cached _valid_count on the grid.
            solid = int(grid._valid_count(coord))
        else:
            solid = grid.cached_solid_count(coord, arr)
        return arr, solid, bool(was_full)

    records = impl.voxel(
        float(grid.bounds.min_x),
        float(grid.bounds.min_y),
        float(grid.bounds.min_z),
        float(grid.voxel_size),
        int(grid.chunk_size),
        int(grid.nx),
        int(grid.ny),
        int(grid.nz),
        int(grid.n_chunks_x),
        int(grid.n_chunks_y),
        int(grid.n_chunks_z),
        len(segments),
        p0,
        p1,
        a0,
        a1,
        zs,
        rs,
        get_chunk,
    )
    dirty: set[tuple[int, int, int]] = set()
    for cx, cy, cz, solid, hits, was_full in records:
        coord = ChunkCoord(int(cx), int(cy), int(cz))
        if int(hits) <= 0:
            if int(was_full):
                grid.release_unmodified_full(coord)
            continue
        arr = grid._chunks.get(coord.as_tuple())
        if isinstance(arr, np.ndarray):
            grid.note_solid_count(coord, int(solid))
            grid.maybe_collapse_chunk(coord, arr, solid_count=int(solid))
        dirty.add(coord.as_tuple())
    return dirty


def _as_f64(values) -> np.ndarray:
    return np.ascontiguousarray(values, dtype=np.float64)


def paint_laser(
    intensity: np.ndarray,
    u0,
    v0,
    u1,
    v1,
    burn,
    radius: float,
    *,
    cell_u: float,
    cell_v: float,
    origin_u: float,
    origin_v: float,
    wrap_v: bool = False,
    v_period: float = 0.0,
    v_scale: float = 1.0,
    allow: np.ndarray | None = None,
    allow_origin: tuple[int, int] = (0, 0),
    occ_kind: int = 0,
    occ: np.ndarray | None = None,
    occ_min_x: float = 0.0,
    occ_min_y: float = 0.0,
    occ_cell: float = 1.0,
    occ_d_theta: float = 1.0,
    occ_period: float = 360.0,
    z_or_r=None,
) -> bool:
    """Paint each segment as its own capsule. Returns whether any texel was raised."""
    impl = _require_impl()
    image = np.ascontiguousarray(intensity)
    u0a = _as_f64(u0)
    nseg = int(u0a.shape[0])
    if nseg <= 0:
        return False
    allow_a = None if allow is None else np.ascontiguousarray(allow, dtype=np.uint8)
    occ_a = None if occ is None else np.ascontiguousarray(occ, dtype=np.float32)
    zr = None if z_or_r is None else _as_f64(z_or_r)
    changed = bool(
        impl.laser_paint(
            image,
            int(image.shape[0]),
            int(image.shape[1]),
            float(cell_u),
            float(cell_v),
            float(origin_u),
            float(origin_v),
            1 if wrap_v else 0,
            float(v_period),
            float(v_scale) if v_scale else 1.0,
            nseg,
            u0a,
            _as_f64(v0),
            _as_f64(u1),
            _as_f64(v1),
            np.ascontiguousarray(burn, dtype=np.uint8),
            float(radius),
            allow_a if allow_a is not None else None,
            int(allow_origin[0]),
            int(allow_origin[1]),
            int(occ_kind),
            occ_a if occ_a is not None else None,
            int(occ_a.shape[0]) if occ_a is not None else 0,
            int(occ_a.shape[1]) if occ_a is not None else 0,
            float(occ_min_x),
            float(occ_min_y),
            float(occ_cell),
            float(occ_d_theta),
            float(occ_period),
            zr if zr is not None else None,
        )
    )
    if image is not intensity:
        intensity[...] = image
    return changed


def clear_laser_capsules(
    intensity: np.ndarray,
    u0,
    v0,
    u1,
    v1,
    radius: float,
    *,
    cell_u: float,
    cell_v: float,
    origin_u: float,
    origin_v: float,
    wrap_v: bool = False,
    v_period: float = 0.0,
    v_scale: float = 1.0,
) -> bool:
    """Zero one capsule per segment. Returns whether any texel was cleared."""
    impl = _require_impl()
    image = np.ascontiguousarray(intensity)
    u0a = _as_f64(u0)
    nseg = int(u0a.shape[0])
    if nseg <= 0:
        return False
    changed = bool(
        impl.laser_clear(
            image,
            int(image.shape[0]),
            int(image.shape[1]),
            float(cell_u),
            float(cell_v),
            float(origin_u),
            float(origin_v),
            1 if wrap_v else 0,
            float(v_period),
            float(v_scale) if v_scale else 1.0,
            nseg,
            u0a,
            _as_f64(v0),
            _as_f64(u1),
            _as_f64(v1),
            float(radius),
        )
    )
    if image is not intensity:
        intensity[...] = image
    return changed
