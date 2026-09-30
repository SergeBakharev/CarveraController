/* Heightmap stock: one leftover Z per XY cell. Carving only ever lowers that
 * value. Cannot represent undercuts - that's what the voxel carver is for.
 */
#include "stock_carve_internal.h"

#include <math.h>

static void sc_mark_tile(uint8_t *tile_mask, int nty, int tile, int ix, int iy) {
    int tx;
    int ty;
    if (tile_mask == NULL || tile <= 0) {
        return;
    }
    tx = ix / tile;
    ty = iy / tile;
    if (tx < 0 || ty < 0) {
        return;
    }
    tile_mask[tx * nty + ty] = 1;
}

/* World Z of the cut if the tip is at parameter t along the move. */
static double sc_cut_z_at(
    const ScProfile *profile,
    double t,
    double p0x,
    double p0y,
    double p0z,
    double dx,
    double dy,
    double dz,
    double wx,
    double wy,
    double clamp_r) {
    double ddx = wx - (p0x + t * dx);
    double ddy = wy - (p0y + t * dy);
    double dist_sq = ddx * ddx + ddy * ddy;
    double dist;
    double z_rel;
    if (clamp_r >= 0.0) {
        /* Outside clamp circle: rim sample, skip hypot. */
        if (dist_sq > clamp_r * clamp_r) {
            dist = clamp_r;
        } else {
            dist = sqrt(dist_sq);
        }
    } else {
        /* No clamp: beyond max_r the lookup is INF - skip hypot when exact. */
        double lim = profile->max_r + 1e-9;
        if (dist_sq > lim * lim) {
            return INFINITY;
        }
        dist = sqrt(dist_sq);
    }
    z_rel = sc_sample_z_for_radius(profile, dist);
    return (p0z + t * dz) + z_rel;
}

/* Carve one tip move into the leftover-height grid. */
static void sc_heightmap_one(
    float *heights,
    int nx,
    int ny,
    double min_x,
    double min_y,
    double min_z,
    double cell,
    int tile,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    const ScProfile *profile,
    uint8_t *hit_mask,
    uint8_t *tile_mask,
    int nty,
    ScLaserDecal *laser,
    int *laser_changed) {
    double max_r = profile->max_r;
    double pad;
    double dx, dy, dz, xy_len_sq;
    int ix0, iy0, ix1, iy1, ix, iy;
    if (max_r <= 0.0) {
        return;
    }
    /* Only visit cells the tool could possibly reach. */
    pad = max_r + cell;
    ix0 = (int)floor(((fmin(p0x, p1x) - pad) - min_x) / cell);
    iy0 = (int)floor(((fmin(p0y, p1y) - pad) - min_y) / cell);
    ix1 = (int)floor(((fmax(p0x, p1x) + pad) - min_x) / cell);
    iy1 = (int)floor(((fmax(p0y, p1y) + pad) - min_y) / cell);
    if (ix0 < 0) {
        ix0 = 0;
    }
    if (iy0 < 0) {
        iy0 = 0;
    }
    if (ix1 > nx - 1) {
        ix1 = nx - 1;
    }
    if (iy1 > ny - 1) {
        iy1 = ny - 1;
    }
    if (ix0 > ix1 || iy0 > iy1) {
        return;
    }
    dx = p1x - p0x;
    dy = p1y - p0y;
    dz = p1z - p0z;
    xy_len_sq = dx * dx + dy * dy;
    for (ix = ix0; ix <= ix1; ix++) {
        double wx = min_x + ((double)ix + 0.5) * cell;
        for (iy = iy0; iy <= iy1; iy++) {
            double wy = min_y + ((double)iy + 0.5) * cell;
            float *hp = &heights[ix * ny + iy];
            double h = (double)(*hp);
            double cut;
            if (!(h > SC_OUTSIDE * 0.5)) {
                continue; /* cell is not stock */
            }
            if (xy_len_sq < 1e-18) {
                /* Stationary in XY: distance to the tip, then look up cut height. */
                double dist = hypot(wx - p0x, wy - p0y);
                double tip_z = p0z < p1z ? p0z : p1z;
                cut = tip_z + sc_sample_z_for_radius(profile, dist);
            } else {
                /* t_lo..t_hi is the stretch of the move where the tool still covers this cell. */
                double t_proj = ((wx - p0x) * dx + (wy - p0y) * dy) / xy_len_sq;
                double px = wx - (p0x + t_proj * dx);
                double py = wy - (p0y + t_proj * dy);
                double dist_perp_sq = px * px + py * py;
                double r_cov = max_r + 1e-9;
                double r_cov_sq = r_cov * r_cov;
                double delta_t;
                double t_lo;
                double t_hi;
                double t_mid;
                /* Far from the path: skip sqrt and the three ball/V samples. */
                if (dist_perp_sq > r_cov_sq) {
                    continue;
                }
                delta_t = sqrt((r_cov_sq - dist_perp_sq) / xy_len_sq);
                t_lo = fmax(t_proj - delta_t, 0.0);
                t_hi = fmin(t_proj + delta_t, 1.0);
                /* Same reject as before: need a non-empty [t_lo, t_hi] on the segment. */
                if (t_lo > t_hi) {
                    continue;
                }
                t_mid = sc_clamp(t_proj, 0.0, 1.0);
                if (profile->const_r >= 0.0) {
                    /* End mill: deepest cut is at the lowest tip along that stretch. */
                    double t_z = dz >= 0.0 ? t_lo : t_hi;
                    cut = (p0z + t_z * dz) + profile->zs[0];
                } else {
                    /* Ball / V: sample both ends plus the closest point, keep the deepest. */
                    double c0 = sc_cut_z_at(profile, t_lo, p0x, p0y, p0z, dx, dy, dz, wx, wy, max_r);
                    double c1 = sc_cut_z_at(profile, t_hi, p0x, p0y, p0z, dx, dy, dz, wx, wy, max_r);
                    double c2 = sc_cut_z_at(profile, t_mid, p0x, p0y, p0z, dx, dy, dz, wx, wy, max_r);
                    cut = c0;
                    if (c1 < cut) {
                        cut = c1;
                    }
                    if (c2 < cut) {
                        cut = c2;
                    }
                }
            }
            if (cut < min_z) {
                cut = min_z;
            }
            if (!isfinite(cut) || !(cut < h)) {
                continue;
            }
            {
                float cut32 = (float)cut;
                if (cut32 < *hp) {
                    *hp = cut32;
                }
            }
            if (hit_mask != NULL) {
                hit_mask[ix * ny + iy] = 1;
            }
            if (laser != NULL) {
                sc_laser_clear_coarse_cell(laser, ix, iy, min_x, min_y, cell, cell, 0, laser_changed);
            }
            sc_mark_tile(tile_mask, nty, tile, ix, iy);
        }
    }
}

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
    int *laser_changed) {
    int i;
    (void)ntx;
    if (heights == NULL || profile == NULL || nseg <= 0 || nx <= 0 || ny <= 0) {
        return 0;
    }
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        sc_heightmap_one(
            heights,
            nx,
            ny,
            min_x,
            min_y,
            min_z,
            cell,
            tile,
            a[0],
            a[1],
            a[2],
            b[0],
            b[1],
            b[2],
            profile,
            hit_mask,
            tile_mask,
            nty,
            laser,
            laser_changed);
    }
    return 0;
}
