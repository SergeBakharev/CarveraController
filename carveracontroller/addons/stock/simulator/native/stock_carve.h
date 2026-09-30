/* Native stock carving: lower leftover material as the cutter moves.
 *
 * Three models:
 *   heightmap   - leftover top Z per XY cell (no undercuts)
 *   cylindrical - leftover radius at (X, angle) for rotary / lathe work
 *   voxel       - 3D cubes, for undercuts and a spinning A axis
 *
 * C99 only: no NumPy headers, no OpenMP, no VLAs.
 */
#ifndef CARVERA_STOCK_CARVE_H
#define CARVERA_STOCK_CARVE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SC_INF 1.0e30
#define SC_OUTSIDE (-1.0e30) /* heightmap cell that is not stock */
#define SC_EMPTY_R (-1.0)

/* Tool side-profile: radius at each height above the tip. */
typedef struct ScProfile {
    const double *zs;
    const double *rs;
    int n;
    double max_r;   /* widest radius - skip cells farther than this */
    double min_r;   /* narrowest radius - filled by sc_profile_prepare */
    double flute_z; /* cutting length (last z sample) */
    double const_r; /* >= 0 if this is a plain cylinder; else < 0 */
    int mono_r;     /* 1 if radius never shrinks going up the tool */
} ScProfile;

/* Voxel grid layout. Cubes are grouped into chunks of `chunk`^3. */
typedef struct ScVoxelGrid {
    double min_x, min_y, min_z;
    double voxel;
    int chunk;
    int nx, ny, nz;
    int ncx, ncy, ncz;
} ScVoxelGrid;

/* One loaded chunk. `solid` is how many cubes still have material. */
typedef struct ScChunkRec {
    int cx, cy, cz;
    uint8_t *data;
    int solid;    /* cubes still holding material */
    int was_full; /* 1 if the chunk started fully solid */
    int hits;     /* cubes removed during this batch */
} ScChunkRec;

/* Ask the host for a chunk. Return 1 and fill data/solid/was_full, or 0 if empty. */
typedef int (*ScGetChunkFn)(
    void *ctx, int cx, int cy, int cz, uint8_t **data, int *solid, int *was_full);

void sc_profile_prepare(ScProfile *p, const double *zs, const double *rs, int n);

/* Optional dirty-index log for sparse laser checkpoints. Append only on real changes. */
typedef struct ScLaserDirty {
    int32_t *iu;
    int32_t *iv;
    int cap;
    int n;
    int overflow;
} ScLaserDirty;

/* World-space laser decal. `v` is Y (planar) or stock angle in degrees (cylindrical). */
typedef struct ScLaserDecal {
    uint8_t *intensity;
    int nx;
    int nv;
    double cell_u;
    double cell_v;
    double origin_u;
    double origin_v;
    int wrap_v;
    double v_period;
    double v_scale;
    ScLaserDirty *dirty; /* optional; NULL skips logging */
} ScLaserDecal;

/* Optional occupancy test so a beam does not paint air.
 * kind 0: no test. 1: heightmap top Z. 2: cylindrical leftover radius.
 * `z_or_r` on each paint segment is the beam Z (heightmap) or min tool radius (cylindrical).
 */
typedef struct ScLaserOcc {
    int kind;
    const float *data;
    int nx;
    int nv;
    double min_x;
    double min_y;
    double cell;
    double d_theta;
    double period;
} ScLaserOcc;

/* Lower leftover heights for a batch of tip moves p0[i] -> p1[i]. */
int sc_heightmap_carve(
    float *heights,
    int nx,
    int ny,
    double min_x,
    double min_y,
    double min_z,
    double cell,
    int tile,
    const double *p0,
    const double *p1,
    int nseg,
    const ScProfile *profile,
    uint8_t *hit_mask,
    uint8_t *tile_mask,
    int ntx,
    int nty,
    ScLaserDecal *laser,
    int *laser_changed);

/* Lower leftover radii. a0/a1 are A-axis angles at the two ends of each move. */
int sc_cylindrical_carve(
    float *radii,
    int nx,
    int n_theta,
    double min_x,
    double cell,
    double d_theta,
    double axis_y,
    double axis_z,
    double stock_radius,
    const double *sin_t,
    const double *cos_t,
    int tile,
    const double *p0,
    const double *p1,
    const double *a0,
    const double *a1,
    int nseg,
    const ScProfile *profile,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntx,
    int ntt,
    ScLaserDecal *laser,
    int *laser_changed);

/* Paint each segment as its own capsule. Burn 0 is skipped (not a clear).
 * `allow`, when set, is a uint8 window whose [0, 0] lies at laser index (allow_u0, allow_v0).
 * Returns 0. Sets *changed when a texel is raised.
 */
int sc_laser_paint(
    ScLaserDecal *map,
    const double *u0,
    const double *v0,
    const double *u1,
    const double *v1,
    const uint8_t *burn,
    const double *z_or_r,
    int nseg,
    double radius,
    const uint8_t *allow,
    int allow_u0,
    int allow_v0,
    int allow_rows,
    int allow_cols,
    const ScLaserOcc *occ,
    int *changed);

/* Zero a capsule per segment (mill-over-engrave on the voxel carver). */
int sc_laser_clear_capsules(
    ScLaserDecal *map,
    const double *u0,
    const double *v0,
    const double *u1,
    const double *v1,
    int nseg,
    double radius,
    int *changed);

/* Zero laser texels whose centers fall in one occupancy cell.
 * `coarse_nv` > 0 and `wrap_v` selects the cylindrical angle bin.
 */
void sc_laser_clear_coarse_cell(
    ScLaserDecal *laser,
    int ix,
    int coarse_iv,
    double coarse_origin_u,
    double coarse_origin_v,
    double coarse_du,
    double coarse_dv,
    int coarse_nv,
    int *changed);

/* Delete cubes inside the tool. `get_chunk` loads occupancy from the host. */
int sc_voxel_carve(
    const ScVoxelGrid *grid,
    const double *p0,
    const double *p1,
    const double *a0,
    const double *a1,
    int nseg,
    const ScProfile *profile,
    ScGetChunkFn get_chunk,
    void *ctx,
    ScChunkRec **touched,
    int *n_touched);

#ifdef __cplusplus
}
#endif

#endif
