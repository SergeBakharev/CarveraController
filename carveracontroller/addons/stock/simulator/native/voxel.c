/* Voxel stock: cubes of material grouped into chunks. A cube is either there
 * or gone. Handles undercuts and A-axis rotation that the heightmap cannot.
 */
#include "stock_carve_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SC_MAX_DA 2.0 /* split a move if A turns more than this many degrees */

static int sc_on_seg(double px, double py, double qx, double qy, double rx, double ry) {
    return fmin(px, rx) - 1e-12 <= qx && qx <= fmax(px, rx) + 1e-12 && fmin(py, ry) - 1e-12 <= qy &&
        qy <= fmax(py, ry) + 1e-12;
}

static int sc_segments_intersect(double ax, double ay, double bx, double by, double cx, double cy, double dx, double dy) {
    double a1 = (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
    double a2 = (by - ay) * (dx - bx) - (bx - ax) * (dy - by);
    double a3 = (dy - cy) * (ax - dx) - (dx - cx) * (ay - dy);
    double a4 = (dy - cy) * (bx - dx) - (dx - cx) * (by - dy);
    int s1 = a1 > 0.0;
    int s1n = a1 < 0.0;
    int s2 = a2 > 0.0;
    int s2n = a2 < 0.0;
    int s3 = a3 > 0.0;
    int s3n = a3 < 0.0;
    int s4 = a4 > 0.0;
    int s4n = a4 < 0.0;
    if (((s1 && s2n) || (s1n && s2)) && ((s3 && s4n) || (s3n && s4))) {
        return 1;
    }
    if (fabs(a1) <= 1e-12 && sc_on_seg(ax, ay, cx, cy, bx, by)) {
        return 1;
    }
    if (fabs(a2) <= 1e-12 && sc_on_seg(ax, ay, dx, dy, bx, by)) {
        return 1;
    }
    if (fabs(a3) <= 1e-12 && sc_on_seg(cx, cy, ax, ay, dx, dy)) {
        return 1;
    }
    return fabs(a4) <= 1e-12 && sc_on_seg(cx, cy, bx, by, dx, dy);
}

static double sc_point_to_aabb(double px, double py, double xmin, double ymin, double xmax, double ymax) {
    double cx = sc_clamp(px, xmin, xmax);
    double cy = sc_clamp(py, ymin, ymax);
    return hypot(px - cx, py - cy);
}

static double sc_point_to_seg(double px, double py, double ax, double ay, double bx, double by) {
    double abx = bx - ax;
    double aby = by - ay;
    double ab_len_sq = abx * abx + aby * aby;
    double t, qx, qy;
    if (ab_len_sq < 1e-18) {
        return hypot(px - ax, py - ay);
    }
    t = sc_clamp(((px - ax) * abx + (py - ay) * aby) / ab_len_sq, 0.0, 1.0);
    qx = ax + t * abx;
    qy = ay + t * aby;
    return hypot(px - qx, py - qy);
}

/* How close a 2D tool path comes to a chunk's XY box. 0 means it overlaps. */
static double sc_segment_aabb_dist(
    double ax, double ay, double bx, double by, double xmin, double ymin, double xmax, double ymax) {
    double d;
    int e;
    double edges[4][4] = {
        {xmin, ymin, xmax, ymin},
        {xmax, ymin, xmax, ymax},
        {xmax, ymax, xmin, ymax},
        {xmin, ymax, xmin, ymin},
    };
    double corners[4][2] = {{xmin, ymin}, {xmax, ymin}, {xmax, ymax}, {xmin, ymax}};
    if ((xmin <= ax && ax <= xmax && ymin <= ay && ay <= ymax) || (xmin <= bx && bx <= xmax && ymin <= by && by <= ymax)) {
        return 0.0;
    }
    for (e = 0; e < 4; e++) {
        if (sc_segments_intersect(ax, ay, bx, by, edges[e][0], edges[e][1], edges[e][2], edges[e][3])) {
            return 0.0;
        }
    }
    d = fmin(sc_point_to_aabb(ax, ay, xmin, ymin, xmax, ymax), sc_point_to_aabb(bx, by, xmin, ymin, xmax, ymax));
    for (e = 0; e < 4; e++) {
        double pd = sc_point_to_seg(corners[e][0], corners[e][1], ax, ay, bx, by);
        if (pd < d) {
            d = pd;
        }
    }
    return d;
}

/* Spin Y/Z with a precomputed cos/sin pair (avoids cos/sin per voxel). */
static void sc_rotate_yz_cs(double y, double z, double c, double s, double *oy, double *oz) {
    *oy = y * c - z * s;
    *oz = y * s + z * c;
}

/* Rotate a box around X so we can test it in the tool's frame. */
static void sc_rotate_aabb_cs(
    double min_x,
    double min_y,
    double min_z,
    double max_x,
    double max_y,
    double max_z,
    double c,
    double s,
    double *o_min_y,
    double *o_min_z,
    double *o_max_y,
    double *o_max_z) {
    double ys[4], zs[4];
    int i, k = 0;
    double y0, z0;
    for (i = 0; i < 2; i++) {
        double y = i ? max_y : min_y;
        int j;
        for (j = 0; j < 2; j++) {
            double z = j ? max_z : min_z;
            sc_rotate_yz_cs(y, z, c, s, &y0, &z0);
            ys[k] = y0;
            zs[k] = z0;
            k++;
        }
    }
    *o_min_y = ys[0];
    *o_max_y = ys[0];
    *o_min_z = zs[0];
    *o_max_z = zs[0];
    for (i = 1; i < 4; i++) {
        if (ys[i] < *o_min_y) {
            *o_min_y = ys[i];
        }
        if (ys[i] > *o_max_y) {
            *o_max_y = ys[i];
        }
        if (zs[i] < *o_min_z) {
            *o_min_z = zs[i];
        }
        if (zs[i] > *o_max_z) {
            *o_max_z = zs[i];
        }
    }
    (void)min_x;
    (void)max_x;
}

static int sc_world_voxel(double x, double origin, double vs) {
    return (int)floor((x - origin) / vs);
}

typedef struct ScChunkTable {
    ScChunkRec *items;
    int n;
    int cap;
} ScChunkTable;

/* Segment fields shared by every voxel test in one constant-A pass. */
typedef struct ScSegTool {
    double p0x, p0y, p0z;
    double p1x, p1y, p1z;
    double dx, dy, dz;
    double xy_len_sq;
    double seg_len_sq;
    double z0, z1;
    const ScProfile *profile;
} ScSegTool;

/* Close enough in XY, and at a height the flute actually covers.
 * Mirrors sc_inside_from_xy in profile.c (keep in sync). */
static int sc_inside_from_xy_local(
    const ScProfile *profile,
    int window_ok,
    double dist_xy,
    int use_band,
    double z_rel,
    double band_lo,
    double band_hi) {
    double eps = 1e-9;
    double radii;
    if (!window_ok || dist_xy > profile->max_r + eps) {
        return 0;
    }
    if (profile->const_r >= 0.0) {
        return profile->const_r > 0.0;
    }
    if (use_band) {
        radii = sc_max_radius_in_band(profile, band_lo, band_hi);
        return dist_xy <= radii + eps && radii > 0.0;
    }
    radii = sc_sample_radius(profile, z_rel);
    return dist_xy <= radii + eps && radii > 0.0;
}

/* Same inclusion test as sc_point_inside_tool (profile.c), with dx/dy/dz and
 * segment lengths already computed for this pass. Keep in sync with
 * sc_point_inside_tool. */
static int sc_point_inside_tool_pre(const ScSegTool *seg, double x, double y, double z) {
    const ScProfile *profile = seg->profile;
    double dx = seg->dx;
    double dy = seg->dy;
    double dz = seg->dz;
    double xy_len_sq = seg->xy_len_sq;
    double seg_len_sq = seg->seg_len_sq;
    double z0 = seg->z0;
    double z1 = seg->z1;
    double eps = 1e-9;
    double dist;
    double z_rel;
    int window;

    if (seg_len_sq < 1e-18) {
        /* Stationary: treat the tool as sitting at p0. */
        z_rel = z - seg->p0z;
        dist = hypot(x - seg->p0x, y - seg->p0y);
        window = profile->n > 0 && z_rel >= z0 - eps && z_rel <= z1 + eps;
        return sc_inside_from_xy_local(profile, window, dist, 0, z_rel, 0.0, 0.0);
    }
    if (xy_len_sq < 1e-18) {
        /* Straight plunge: the tip slides in Z, so take the widest flute in that band. */
        double tip_lo = seg->p0z < seg->p0z + dz ? seg->p0z : seg->p0z + dz;
        double tip_hi = seg->p0z > seg->p0z + dz ? seg->p0z : seg->p0z + dz;
        double band_lo = z - tip_hi;
        double band_hi = z - tip_lo;
        if (band_lo < z0) {
            band_lo = z0;
        }
        if (band_hi > z1) {
            band_hi = z1;
        }
        window = band_lo <= band_hi + eps;
        dist = hypot(x - seg->p0x, y - seg->p0y);
        return sc_inside_from_xy_local(profile, window, dist, 1, 0.0, band_lo, band_hi);
    }
    {
        /* General move: project onto the XY path, then clamp to where the flute
         * can still reach this Z. */
        double t_lo, t_hi, t;
        double tip_x, tip_y, tip_z;
        if (fabs(dz) < 1e-18) {
            z_rel = z - seg->p0z;
            window = z_rel >= z0 - eps && z_rel <= z1 + eps;
            t_lo = window ? 0.0 : 1.0;
            t_hi = window ? 1.0 : 0.0;
        } else {
            double t_a = (z - z1 - seg->p0z) / dz;
            double t_b = (z - z0 - seg->p0z) / dz;
            double lo = t_a < t_b ? t_a : t_b;
            double hi = t_a > t_b ? t_a : t_b;
            t_lo = lo > 0.0 ? lo : 0.0;
            t_hi = hi < 1.0 ? hi : 1.0;
            window = t_lo <= t_hi + eps;
        }
        t = ((x - seg->p0x) * dx + (y - seg->p0y) * dy) / xy_len_sq;
        if (t < t_lo) {
            t = t_lo;
        }
        if (t > t_hi) {
            t = t_hi;
        }
        tip_x = seg->p0x + t * dx;
        tip_y = seg->p0y + t * dy;
        tip_z = seg->p0z + t * dz;
        z_rel = z - tip_z;
        dist = hypot(x - tip_x, y - tip_y);
        return sc_inside_from_xy_local(profile, window, dist, 0, z_rel, 0.0, 0.0);
    }
}

/* Load a chunk from the host once, then reuse it for the rest of this batch. */
static ScChunkRec *sc_chunk_get(
    ScChunkTable *table, ScGetChunkFn get_chunk, void *ctx, int cx, int cy, int cz, int cs) {
    int i;
    ScChunkRec *rec;
    uint8_t *data = NULL;
    int solid = 0;
    int was_full = 0;
    for (i = 0; i < table->n; i++) {
        if (table->items[i].cx == cx && table->items[i].cy == cy && table->items[i].cz == cz) {
            return &table->items[i];
        }
    }
    if (!get_chunk(ctx, cx, cy, cz, &data, &solid, &was_full) || data == NULL) {
        return NULL;
    }
    if (table->n >= table->cap) {
        int cap = table->cap ? table->cap * 2 : 32;
        ScChunkRec *grown = (ScChunkRec *)realloc(table->items, (size_t)cap * sizeof(ScChunkRec));
        if (grown == NULL) {
            return NULL;
        }
        table->items = grown;
        table->cap = cap;
    }
    rec = &table->items[table->n++];
    rec->cx = cx;
    rec->cy = cy;
    rec->cz = cz;
    rec->data = data;
    rec->solid = solid;
    rec->was_full = was_full;
    rec->hits = 0;
    (void)cs;
    return rec;
}

/* True when every in-bounds voxel center of this chunk sits inside a const_r
 * (plain cylinder) sweep at A≈0. Convex swept volume ⇒ 8 AABB corners suffice.
 * Ball/V and rotating A must not use this path. */
static int sc_chunk_fully_inside_const_r(
    const ScVoxelGrid *grid,
    int cx,
    int cy,
    int cz,
    const ScSegTool *seg) {
    int cs = grid->chunk;
    double vs = grid->voxel;
    int nx_local = grid->nx - cx * cs;
    int ny_local = grid->ny - cy * cs;
    int nz_local = grid->nz - cz * cs;
    double x0, y0, z0c, x1, y1, z1c;
    int i;
    if (nx_local > cs) {
        nx_local = cs;
    }
    if (ny_local > cs) {
        ny_local = cs;
    }
    if (nz_local > cs) {
        nz_local = cs;
    }
    if (nx_local <= 0 || ny_local <= 0 || nz_local <= 0) {
        return 0;
    }
    /* AABB of in-bounds voxel centers (padding outside nx/ny/nz is ignored). */
    x0 = grid->min_x + ((double)(cx * cs) + 0.5) * vs;
    y0 = grid->min_y + ((double)(cy * cs) + 0.5) * vs;
    z0c = grid->min_z + ((double)(cz * cs) + 0.5) * vs;
    x1 = grid->min_x + ((double)(cx * cs + nx_local - 1) + 0.5) * vs;
    y1 = grid->min_y + ((double)(cy * cs + ny_local - 1) + 0.5) * vs;
    z1c = grid->min_z + ((double)(cz * cs + nz_local - 1) + 0.5) * vs;
    for (i = 0; i < 8; i++) {
        double x = (i & 1) ? x1 : x0;
        double y = (i & 2) ? y1 : y0;
        double z = (i & 4) ? z1c : z0c;
        if (!sc_point_inside_tool_pre(seg, x, y, z)) {
            return 0;
        }
    }
    return 1;
}

/* Zero every voxel in the chunk; padding was already empty. hits/solid match a
 * per-voxel walk that would have removed every remaining solid cube. */
static void sc_chunk_clear_all(ScChunkRec *rec, int cs) {
    size_t n = (size_t)cs * (size_t)cs * (size_t)cs;
    if (rec->solid > 0) {
        rec->hits += rec->solid;
        rec->solid = 0;
    }
    memset(rec->data, 0, n);
}

/* Carve one move at a fixed A angle. Skip chunks that can't possibly touch the tool. */
static void sc_carve_constant_a(
    const ScVoxelGrid *grid,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double angle,
    const ScProfile *profile,
    ScChunkTable *table,
    ScGetChunkFn get_chunk,
    void *ctx) {
    double max_r = profile->max_r;
    double flute = profile->flute_z;
    double vs = grid->voxel;
    int cs = grid->chunk;
    double pad = max_r + vs;
    double minx = fmin(p0x, p1x) - pad;
    double miny = fmin(p0y, p1y) - pad;
    double minz = fmin(p0z, p1z) - pad;
    double maxx = fmax(p0x, p1x) + pad;
    double maxy = fmax(p0y, p1y) + pad;
    double maxz = fmax(p0z, p1z) + flute + pad;
    double tip_z_lo = fmin(p0z, p1z) - vs;
    double tip_z_hi = fmax(p0z, p1z) + flute + vs;
    double xy_reject = max_r + vs;
    int rotate = fabs(angle) > 1e-9;
    int ix0, iy0, iz0, ix1, iy1, iz1;
    int cx0, cy0, cz0, cx1, cy1, cz1;
    int cx, cy, cz;
    double cos_a = 1.0, sin_a = 0.0;
    int allow_full_clear;
    ScSegTool seg;
    seg.p0x = p0x;
    seg.p0y = p0y;
    seg.p0z = p0z;
    seg.p1x = p1x;
    seg.p1y = p1y;
    seg.p1z = p1z;
    seg.dx = p1x - p0x;
    seg.dy = p1y - p0y;
    seg.dz = p1z - p0z;
    seg.xy_len_sq = seg.dx * seg.dx + seg.dy * seg.dy;
    seg.seg_len_sq = seg.xy_len_sq + seg.dz * seg.dz;
    seg.z0 = profile->n ? profile->zs[0] : 0.0;
    seg.z1 = profile->n ? profile->zs[profile->n - 1] : 0.0;
    seg.profile = profile;
    /* Plain cylinder at A≈0: convex sweep, safe to clear a fully covered chunk. */
    allow_full_clear = (!rotate && profile->const_r > 0.0);
    if (rotate) {
        double rad = angle * (M_PI / 180.0);
        double ry0, rz0, ry1, rz1;
        cos_a = cos(rad);
        sin_a = sin(rad);
        /* Spin the search box into world space if A is not zero. */
        sc_rotate_aabb_cs(minx, miny, minz, maxx, maxy, maxz, cos_a, sin_a, &ry0, &rz0, &ry1, &rz1);
        miny = ry0;
        minz = rz0;
        maxy = ry1;
        maxz = rz1;
    }
    ix0 = sc_world_voxel(minx, grid->min_x, vs);
    iy0 = sc_world_voxel(miny, grid->min_y, vs);
    iz0 = sc_world_voxel(minz, grid->min_z, vs);
    ix1 = sc_world_voxel(maxx, grid->min_x, vs);
    iy1 = sc_world_voxel(maxy, grid->min_y, vs);
    iz1 = sc_world_voxel(maxz, grid->min_z, vs);
    if (ix0 < 0) {
        ix0 = 0;
    }
    if (iy0 < 0) {
        iy0 = 0;
    }
    if (iz0 < 0) {
        iz0 = 0;
    }
    if (ix1 > grid->nx - 1) {
        ix1 = grid->nx - 1;
    }
    if (iy1 > grid->ny - 1) {
        iy1 = grid->ny - 1;
    }
    if (iz1 > grid->nz - 1) {
        iz1 = grid->nz - 1;
    }
    if (ix0 > grid->nx - 1 || iy0 > grid->ny - 1 || iz0 > grid->nz - 1) {
        return;
    }
    cx0 = ix0 / cs;
    cy0 = iy0 / cs;
    cz0 = iz0 / cs;
    cx1 = ix1 / cs;
    cy1 = iy1 / cs;
    cz1 = iz1 / cs;
    for (cx = cx0; cx <= cx1; cx++) {
        for (cy = cy0; cy <= cy1; cy++) {
            for (cz = cz0; cz <= cz1; cz++) {
                double ox, oy, oz, cx1w, cy1w, cz1w;
                double mx0, my0, mz0, mx1, my1, mz1;
                ScChunkRec *rec;
                int ix, iy, iz;
                if (cx < 0 || cy < 0 || cz < 0 || cx >= grid->ncx || cy >= grid->ncy || cz >= grid->ncz) {
                    continue;
                }
                ox = grid->min_x + (double)cx * cs * vs;
                oy = grid->min_y + (double)cy * cs * vs;
                oz = grid->min_z + (double)cz * cs * vs;
                cx1w = ox + cs * vs;
                cy1w = oy + cs * vs;
                cz1w = oz + cs * vs;
                if (rotate) {
                    /* Unspin chunk box by -A using cached cos(A), -sin(A). */
                    sc_rotate_aabb_cs(ox, oy, oz, cx1w, cy1w, cz1w, cos_a, -sin_a, &my0, &mz0, &my1, &mz1);
                    mx0 = ox;
                    mx1 = cx1w;
                    /* Cheap reject: wrong Z band, or the path is farther than the tool radius. */
                    if (mz1 < tip_z_lo || mz0 > tip_z_hi) {
                        continue;
                    }
                    if (sc_segment_aabb_dist(p0x, p0y, p1x, p1y, mx0, my0, mx1, my1) > xy_reject) {
                        continue;
                    }
                } else {
                    if (cz1w < tip_z_lo || oz > tip_z_hi) {
                        continue;
                    }
                    if (sc_segment_aabb_dist(p0x, p0y, p1x, p1y, ox, oy, cx1w, cy1w) > xy_reject) {
                        continue;
                    }
                }
                rec = sc_chunk_get(table, get_chunk, ctx, cx, cy, cz, cs);
                if (rec == NULL || rec->solid <= 0 || rec->data == NULL) {
                    continue;
                }
                if (allow_full_clear && sc_chunk_fully_inside_const_r(grid, cx, cy, cz, &seg)) {
                    sc_chunk_clear_all(rec, cs);
                    continue;
                }
                /* Test each remaining cube against the swept tool. */
                for (ix = 0; ix < cs; ix++) {
                    int gx = cx * cs + ix;
                    if (gx >= grid->nx) {
                        continue;
                    }
                    for (iy = 0; iy < cs; iy++) {
                        int gy = cy * cs + iy;
                        if (gy >= grid->ny) {
                            continue;
                        }
                        for (iz = 0; iz < cs; iz++) {
                            int gz = cz * cs + iz;
                            size_t idx;
                            double x, y, z;
                            if (gz >= grid->nz) {
                                continue;
                            }
                            idx = ((size_t)ix * (size_t)cs + (size_t)iy) * (size_t)cs + (size_t)iz;
                            if (!rec->data[idx]) {
                                continue;
                            }
                            x = grid->min_x + ((double)gx + 0.5) * vs;
                            y = grid->min_y + ((double)gy + 0.5) * vs;
                            z = grid->min_z + ((double)gz + 0.5) * vs;
                            if (rotate) {
                                /* Test in the tool's frame: unspin the cube by -A. */
                                sc_rotate_yz_cs(y, z, cos_a, -sin_a, &y, &z);
                            }
                            if (!sc_point_inside_tool_pre(&seg, x, y, z)) {
                                continue;
                            }
                            rec->data[idx] = 0;
                            rec->solid -= 1;
                            rec->hits += 1;
                            if (rec->solid < 0) {
                                rec->solid = 0;
                            }
                        }
                    }
                }
            }
        }
    }
}

static int sc_carve_segment(
    const ScVoxelGrid *grid,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1,
    const ScProfile *profile,
    ScChunkTable *table,
    ScGetChunkFn get_chunk,
    void *ctx) {
    double da = a1 - a0;
    /* Big A changes get split so each piece can be treated as a fixed rotation. */
    if (fabs(da) > SC_MAX_DA) {
        int n = (int)ceil(fabs(da) / SC_MAX_DA);
        int i;
        if (n < 1) {
            n = 1;
        }
        for (i = 0; i < n; i++) {
            double t0 = (double)i / (double)n;
            double t1 = (double)(i + 1) / (double)n;
            double ang = a0 + 0.5 * (t0 + t1) * da;
            double dx = p1x - p0x;
            double dy = p1y - p0y;
            double dz = p1z - p0z;
            sc_carve_constant_a(
                grid,
                p0x + t0 * dx,
                p0y + t0 * dy,
                p0z + t0 * dz,
                p0x + t1 * dx,
                p0y + t1 * dy,
                p0z + t1 * dz,
                ang,
                profile,
                table,
                get_chunk,
                ctx);
        }
        return 0;
    }
    sc_carve_constant_a(grid, p0x, p0y, p0z, p1x, p1y, p1z, a0, profile, table, get_chunk, ctx);
    return 0;
}

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
    int *n_touched) {
    ScChunkTable table;
    int i;
    if (touched) {
        *touched = NULL;
    }
    if (n_touched) {
        *n_touched = 0;
    }
    if (grid == NULL || profile == NULL || nseg <= 0 || get_chunk == NULL) {
        return 0;
    }
    if (profile->max_r <= 0.0 && profile->flute_z <= 0.0) {
        return 0;
    }
    memset(&table, 0, sizeof(table));
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        double aa = a0 ? a0[i] : 0.0;
        double ab = a1 ? a1[i] : 0.0;
        if (sc_carve_segment(grid, a[0], a[1], a[2], b[0], b[1], b[2], aa, ab, profile, &table, get_chunk, ctx) != 0) {
            free(table.items);
            return -1;
        }
    }
    if (touched) {
        *touched = table.items;
    } else {
        free(table.items);
    }
    if (n_touched) {
        *n_touched = table.n;
    }
    return 0;
}
