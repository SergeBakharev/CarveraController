/* Tool-shape lookups used by all three carvers. */
#include "stock_carve_internal.h"

#include <math.h>

/* Cache max/min radius, flute length, and whether this is a plain cylinder. */
void sc_profile_prepare(ScProfile *p, const double *zs, const double *rs, int n) {
    double max_r;
    double min_r;
    int i;
    p->zs = zs;
    p->rs = rs;
    p->n = n;
    if (n <= 0) {
        p->max_r = 0.0;
        p->min_r = 0.0;
        p->flute_z = 0.0;
        p->const_r = -1.0;
        p->mono_r = 1;
        return;
    }
    max_r = rs[0];
    min_r = rs[0];
    p->mono_r = 1;
    for (i = 1; i < n; i++) {
        if (rs[i] > max_r) {
            max_r = rs[i];
        }
        if (rs[i] < min_r) {
            min_r = rs[i];
        }
        if (rs[i] < rs[i - 1] - 1e-12) {
            p->mono_r = 0;
        }
    }
    p->max_r = max_r;
    p->min_r = min_r;
    p->flute_z = zs[n - 1];
    p->const_r = (max_r - min_r < 1e-12) ? max_r : -1.0;
}

/* Linear interpolate radius between the two samples that bracket z_rel. */
double sc_sample_radius(const ScProfile *p, double z_rel) {
    int idx;
    double z0, z1, r0, r1, denom, t;
    if (p->n <= 0) {
        return 0.0;
    }
    if (z_rel < p->zs[0] - 1e-9 || z_rel > p->zs[p->n - 1] + 1e-9) {
        return 0.0; /* above or below the flute */
    }
    if (p->n == 1) {
        return p->rs[0];
    }
    idx = 0;
    while (idx < p->n && !(p->zs[idx] > z_rel)) {
        idx++;
    }
    idx -= 1;
    if (idx < 0) {
        idx = 0;
    }
    if (idx > p->n - 2) {
        idx = p->n - 2;
    }
    z0 = p->zs[idx];
    z1 = p->zs[idx + 1];
    r0 = p->rs[idx];
    r1 = p->rs[idx + 1];
    denom = z1 - z0;
    t = 0.0;
    if (fabs(denom) >= 1e-12) {
        t = (z_rel - z0) / denom;
    }
    return r0 + t * (r1 - r0);
}

/* Radii only grow going up: binary search, same bracket/lerp as the old walk. */
static double sc_sample_z_mono(const ScProfile *p, double dist) {
    int lo;
    int hi;
    int idx;
    double r0, r1, z0, z1, denom, t;
    /* First index with rs[i] >= dist (or n if all smaller). */
    lo = 0;
    hi = p->n;
    while (lo < hi) {
        int mid = lo + ((hi - lo) >> 1);
        if (p->rs[mid] < dist) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    idx = lo;
    if (idx >= p->n) {
        idx = p->n - 1;
    }
    if (idx == 0) {
        return p->zs[0];
    }
    r0 = p->rs[idx - 1];
    r1 = p->rs[idx];
    z0 = p->zs[idx - 1];
    z1 = p->zs[idx];
    denom = r1 - r0;
    if (fabs(denom) >= 1e-12) {
        t = sc_clamp((dist - r0) / denom, 0.0, 1.0);
        return z0 + t * (z1 - z0);
    }
    return z0 < z1 ? z0 : z1;
}

/* Inverse of sample_radius: how far up the tool first reaches `dist`.
 * A V-bit can match the same radius twice - pick the lowest Z (deepest cut).
 */
double sc_sample_z_for_radius(const ScProfile *p, double dist) {
    double z_best;
    int i;
    if (p->n <= 0) {
        return INFINITY;
    }
    /* Cylinder: prepare already folded min/max into const_r. */
    if (p->const_r >= 0.0) {
        return dist <= p->const_r + 1e-9 ? p->zs[0] : INFINITY;
    }
    if (dist > p->max_r + 1e-9) {
        return INFINITY;
    }
    if (p->mono_r) {
        return sc_sample_z_mono(p, dist);
    }
    /* Non-mono: same segment walk + vertex pass as before (lowest Z wins). */
    z_best = INFINITY;
    for (i = 0; i < p->n - 1; i++) {
        double z0 = p->zs[i];
        double z1 = p->zs[i + 1];
        double r0 = p->rs[i];
        double r1 = p->rs[i + 1];
        double cand = INFINITY;
        if (dist <= r0 + 1e-9) {
            cand = z0;
        } else if (fabs(r1 - r0) >= 1e-12 && dist <= r1 + 1e-9) {
            double t = sc_clamp((dist - r0) / (r1 - r0), 0.0, 1.0);
            cand = z0 + t * (z1 - z0);
        }
        if (cand < z_best) {
            z_best = cand;
        }
    }
    for (i = 0; i < p->n; i++) {
        if (dist <= p->rs[i] + 1e-9 && p->zs[i] < z_best) {
            z_best = p->zs[i];
        }
    }
    return z_best;
}

/* Widest part of the tool between two heights. */
double sc_max_radius_in_band(const ScProfile *p, double band_lo, double band_hi) {
    double r;
    int i;
    r = sc_sample_radius(p, band_lo);
    {
        double rh = sc_sample_radius(p, band_hi);
        if (rh > r) {
            r = rh;
        }
    }
    if (p->n <= 2) {
        return r;
    }
    for (i = 1; i < p->n - 1; i++) {
        double z = p->zs[i];
        double rk;
        if (z < band_lo - 1e-9 || z > band_hi + 1e-9) {
            continue;
        }
        rk = sc_sample_radius(p, z);
        if (rk > r) {
            r = rk;
        }
    }
    return r;
}

/* Close enough in XY, and at a height the flute actually covers. */
static int sc_inside_from_xy(
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

int sc_point_inside_tool(
    double x,
    double y,
    double z,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    const ScProfile *profile) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double xy_len_sq = dx * dx + dy * dy;
    double seg_len_sq = xy_len_sq + dz * dz;
    double z0 = profile->n ? profile->zs[0] : 0.0;
    double z1 = profile->n ? profile->zs[profile->n - 1] : 0.0;
    double eps = 1e-9;
    double dist;
    double z_rel;
    int window;

    if (seg_len_sq < 1e-18) {
        /* Stationary: treat the tool as sitting at p0. */
        z_rel = z - p0z;
        dist = hypot(x - p0x, y - p0y);
        window = profile->n > 0 && z_rel >= z0 - eps && z_rel <= z1 + eps;
        return sc_inside_from_xy(profile, window, dist, 0, z_rel, 0.0, 0.0);
    }
    if (xy_len_sq < 1e-18) {
        /* Straight plunge: the tip slides in Z, so take the widest flute in that band. */
        double tip_lo = p0z < p0z + dz ? p0z : p0z + dz;
        double tip_hi = p0z > p0z + dz ? p0z : p0z + dz;
        double band_lo = z - tip_hi;
        double band_hi = z - tip_lo;
        if (band_lo < z0) {
            band_lo = z0;
        }
        if (band_hi > z1) {
            band_hi = z1;
        }
        window = band_lo <= band_hi + eps;
        dist = hypot(x - p0x, y - p0y);
        return sc_inside_from_xy(profile, window, dist, 1, 0.0, band_lo, band_hi);
    }
    {
        /* General move: project onto the XY path, then clamp to where the flute
         * can still reach this Z. */
        double t_lo, t_hi, t;
        double tip_x, tip_y, tip_z;
        if (fabs(dz) < 1e-18) {
            z_rel = z - p0z;
            window = z_rel >= z0 - eps && z_rel <= z1 + eps;
            t_lo = window ? 0.0 : 1.0;
            t_hi = window ? 1.0 : 0.0;
        } else {
            double t_a = (z - z1 - p0z) / dz;
            double t_b = (z - z0 - p0z) / dz;
            double lo = t_a < t_b ? t_a : t_b;
            double hi = t_a > t_b ? t_a : t_b;
            t_lo = lo > 0.0 ? lo : 0.0;
            t_hi = hi < 1.0 ? hi : 1.0;
            window = t_lo <= t_hi + eps;
        }
        t = ((x - p0x) * dx + (y - p0y) * dy) / xy_len_sq;
        if (t < t_lo) {
            t = t_lo;
        }
        if (t > t_hi) {
            t = t_hi;
        }
        tip_x = p0x + t * dx;
        tip_y = p0y + t * dy;
        tip_z = p0z + t * dz;
        z_rel = z - tip_z;
        dist = hypot(x - tip_x, y - tip_y);
        return sc_inside_from_xy(profile, window, dist, 0, z_rel, 0.0, 0.0);
    }
}
