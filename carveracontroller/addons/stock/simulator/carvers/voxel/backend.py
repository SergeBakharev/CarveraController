"""Voxel carver backend wrapping the existing chunked occupancy grid."""

from __future__ import annotations

from carveracontroller.addons.stock.simulator.carvers.backend import DEFAULT_TILE_SIZE, CarverBackend, TileKey
from carveracontroller.addons.stock.stock_geometry import StockBounds
from carveracontroller.addons.stock.stock_shape import RectangularStock, StockShape

from .carve import carve_segment_into_grid
from .checkpoints import CheckpointStore, restore_voxel_checkpoint
from .grid import CHUNK_EMPTY, CHUNK_FULL, ChunkCoord, ChunkedVoxelGrid
from .mesher import mesh_dirty_chunks
from .occupancy import expand_dirty_with_neighbors, exterior_chunk_keys, non_full_chunk_keys, seed_shape_occupancy


class VoxelBackend:
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
    ):
        self.bounds = bounds
        self.cell_size = float(cell_size_mm)
        self.chunk_size = int(chunk_size)
        self.shape: StockShape = shape or RectangularStock(
            width_mm=max(bounds.size[0], 1e-6),
            length_mm=max(bounds.size[1], 1e-6),
            height_mm=max(bounds.size[2], 1e-6),
        )
        self.grid = grid if grid is not None else ChunkedVoxelGrid(bounds, cell_size_mm, chunk_size)
        if seed and grid is None:
            seed_shape_occupancy(self.grid, self.shape)

    @property
    def voxel_size(self) -> float:
        return self.cell_size

    def reset_occupancy(self) -> set[TileKey]:
        self.grid.reset()
        seed_shape_occupancy(self.grid, self.shape)
        return self.initial_surface_keys()

    def clone_empty(self) -> VoxelBackend:
        return VoxelBackend(self.bounds, self.cell_size, self.shape, self.chunk_size, seed=True)

    def carve_segment(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        tool_def,
        tool_unit_scale: float = 1.0,
        *,
        a0: float = 0.0,
        a1: float = 0.0,
    ) -> set[TileKey]:
        return carve_segment_into_grid(
            self.grid,
            p0,
            p1,
            tool_def,
            tool_unit_scale=tool_unit_scale,
            a0=a0,
            a1=a1,
        )

    def snapshot_full(self) -> object:
        raw, _nbytes = self.grid.snapshot_non_full()
        return ("full", raw)

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
        return ("delta", delta)

    def restore(self, payload: object) -> set[TileKey]:
        kind, data = payload  # type: ignore[misc]
        if kind == "full":
            self.grid.restore_non_full(data)
            return set(data.keys()) | self.initial_surface_keys()
        # delta: apply on top of current occupancy
        for key, state in data.items():
            if state is CHUNK_FULL:
                self.grid._chunks.pop(key, None)
            elif state is CHUNK_EMPTY:
                self.grid._chunks[key] = CHUNK_EMPTY
            else:
                self.grid._chunks[key] = state.copy() if hasattr(state, "copy") else state
        return set(data.keys())

    def copy_tiles(self, keys: set[TileKey]) -> VoxelBackend:
        copied = self.grid.copy_chunks(keys)
        out = VoxelBackend(
            self.bounds,
            self.cell_size,
            self.shape,
            self.chunk_size,
            grid=copied,
            seed=False,
        )
        return out

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
