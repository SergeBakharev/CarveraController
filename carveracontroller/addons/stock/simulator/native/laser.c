/* Laser decal: paint a beam capsule, and wipe texels a mill has just cut.
 * Strokes stay separate. Merging them into one chord would swallow raster lead-ins.
 */
#include "stock_carve_internal.h"

#include <math.h>

static int sc_mod_int(int a, int m) {
    int r;
    if (m <= 0) {
        return 0;
    }
    r = a % m;
    if (r < 0) {
        r += m;
    }
    return r;
}

static void sc_unwrap_v(double v0, double v1, double period, double *o0, double *o1) {
    double dv;
    if (period <= 0.0) {
        period = 360.0;
    }
    dv = v1 - v0;
    if (fabs(dv) >= period - 1e-6) {
        *o0 = v0;
        *o1 = v0 + period;
        return;
    }
    dv = sc_py_mod(dv + period * 0.5, period) - period * 0.5;
    *o0 = v0;
    *o1 = v0 + dv;
}

static int sc_capsule_hit(
    double uu,
    double vv,
    double u0,
    double v0,
    double u1,
    double v1,
    double radius,
    double v_scale) {
    double scale = v_scale != 0.0 ? v_scale : 1.0;
    double du = u1 - u0;
    double dv = (v1 - v0) * scale;
    double len_sq = du * du + dv * dv;
    double r_cov = radius + 1e-9;
    double vv_mm = vv * scale;
    double v0_mm = v0 * scale;
    double dist_sq;
    double t;
    double px;
    double py;
    if (len_sq < 1e-18) {
        px = uu - u0;
        py = vv_mm - v0_mm;
        return px * px + py * py <= r_cov * r_cov;
    }
    t = ((uu - u0) * du + (vv_mm - v0_mm) * dv) / len_sq;
    if (t < 0.0) {
        t = 0.0;
    } else if (t > 1.0) {
        t = 1.0;
    }
    px = uu - (u0 + t * du);
    py = vv_mm - (v0_mm + t * dv);
    dist_sq = px * px + py * py;
    return dist_sq <= r_cov * r_cov;
}

static int sc_capsule_hit_wrapped(
    double uu,
    double vv,
    double u0,
    double v0,
    double u1,
    double v1,
    double radius,
    double period,
    double v_scale) {
    if (period <= 0.0) {
        period = 360.0;
    }
    if (sc_capsule_hit(uu, vv, u0, v0, u1, v1, radius, v_scale)) {
        return 1;
    }
    if (sc_capsule_hit(uu, vv + period, u0, v0, u1, v1, radius, v_scale)) {
        return 1;
    }
    return sc_capsule_hit(uu, vv - period, u0, v0, u1, v1, radius, v_scale);
}

static int sc_occ_allows(const ScLaserOcc *occ, double z_or_r, double uu, double vv) {
    double eps;
    float thr;
    int ix;
    int iv;
    float sample;
    if (occ == NULL || occ->kind == 0 || occ->data == NULL || occ->nx <= 0 || occ->nv <= 0) {
        return 1;
    }
    eps = occ->cell > 0.2 ? occ->cell : 0.2;
    thr = (float)(z_or_r - eps);
    ix = (int)floor((uu - occ->min_x) / (occ->cell > 1e-12 ? occ->cell : 1e-12));
    if (ix < 0) {
        ix = 0;
    } else if (ix >= occ->nx) {
        ix = occ->nx - 1;
    }
    if (occ->kind == 1) {
        iv = (int)floor((vv - occ->min_y) / (occ->cell > 1e-12 ? occ->cell : 1e-12));
        if (iv < 0) {
            iv = 0;
        } else if (iv >= occ->nv) {
            iv = occ->nv - 1;
        }
        sample = occ->data[(size_t)ix * (size_t)occ->nv + (size_t)iv];
        return (double)sample > SC_OUTSIDE * 0.5 && sample >= thr;
    }
    {
        double period = occ->period > 0.0 ? occ->period : 360.0;
        double wrapped = sc_py_mod(vv, period);
        double step = occ->d_theta > 1e-12 ? occ->d_theta : 1e-12;
        iv = (int)floor(wrapped / step);
        iv = sc_mod_int(iv, occ->nv);
        sample = occ->data[(size_t)ix * (size_t)occ->nv + (size_t)iv];
        return sample >= 0.0f && sample >= thr;
    }
}

static int sc_texel_allowed(
    const uint8_t *allow,
    int au0,
    int av0,
    int a_rows,
    int a_cols,
    const ScLaserOcc *occ,
    double z_or_r,
    int iu,
    int iv,
    double uu,
    double vv) {
    if (allow != NULL) {
        int ar = iu - au0;
        int ac = iv - av0;
        if (ar < 0 || ac < 0 || ar >= a_rows || ac >= a_cols) {
            return 0;
        }
        if (!allow[(size_t)ar * (size_t)a_cols + (size_t)ac]) {
            return 0;
        }
    }
    return sc_occ_allows(occ, z_or_r, uu, vv);
}

/* 1 when the texel changed. */
static int sc_write_texel(ScLaserDecal *map, int iu, int iv, uint8_t value) {
    uint8_t *p = &map->intensity[(size_t)iu * (size_t)map->nv + (size_t)iv];
    if (value) {
        if (*p >= value) {
            return 0;
        }
        *p = value;
        return 1;
    }
    if (!*p) {
        return 0;
    }
    *p = 0;
    return 1;
}

static int sc_laser_stamp_one(
    ScLaserDecal *map,
    double u0,
    double v0,
    double u1,
    double v1,
    uint8_t value,
    double radius,
    const uint8_t *allow,
    int allow_u0,
    int allow_v0,
    int allow_rows,
    int allow_cols,
    const ScLaserOcc *occ,
    double z_or_r,
    int *changed) {
    double cell_u;
    double cell_v;
    double v_scale;
    double pad_u;
    double pad_v;
    double period;
    double v0u;
    double v1u;
    int iu0;
    int iu1;
    int iu;
    int any = 0;
    if (map == NULL || map->intensity == NULL || map->nx <= 0 || map->nv <= 0) {
        return 0;
    }
    cell_u = map->cell_u > 1e-12 ? map->cell_u : 1e-12;
    cell_v = map->cell_v > 1e-12 ? map->cell_v : 1e-12;
    v_scale = map->v_scale != 0.0 ? map->v_scale : 1.0;
    if (radius < 0.71 * map->cell_u) {
        radius = 0.71 * map->cell_u;
    }
    if (radius < 0.0) {
        radius = 0.0;
    }
    pad_u = radius + map->cell_u;
    pad_v = radius / (v_scale > 1e-12 ? v_scale : 1e-12) + map->cell_v;
    iu0 = (int)floor((fmin(u0, u1) - pad_u - map->origin_u) / cell_u);
    iu1 = (int)floor((fmax(u0, u1) + pad_u - map->origin_u) / cell_u);
    if (iu0 < 0) {
        iu0 = 0;
    }
    if (iu1 > map->nx - 1) {
        iu1 = map->nx - 1;
    }
    if (iu0 > iu1) {
        return 0;
    }
    period = map->v_period > 0.0 ? map->v_period : 360.0;
    if (map->wrap_v) {
        double span;
        int full;
        int i0;
        int n;
        int lo;
        int hi;
        int i;
        sc_unwrap_v(v0, v1, period, &v0u, &v1u);
        span = fabs(v1u - v0u) + 2.0 * pad_v;
        full = span >= period - 1e-6;
        if (full) {
            lo = 0;
            hi = map->nv - 1;
        } else {
            double vlo = fmin(v0u, v1u) - pad_v;
            n = (int)ceil(span / cell_v) + 2;
            i0 = (int)floor((vlo - map->origin_v) / cell_v);
            lo = i0;
            hi = i0 + n; /* inclusive: n+1 samples, matching arange(n+1) */
        }
        for (iu = iu0; iu <= iu1; iu++) {
            double uu = map->origin_u + ((double)iu + 0.5) * map->cell_u;
            for (i = lo; i <= hi; i++) {
                int iv = full ? i : sc_mod_int(i, map->nv);
                double vv = map->origin_v + ((double)iv + 0.5) * map->cell_v;
                if (!sc_capsule_hit_wrapped(uu, vv, u0, v0u, u1, v1u, radius, period, v_scale)) {
                    continue;
                }
                if (!sc_texel_allowed(allow, allow_u0, allow_v0, allow_rows, allow_cols, occ, z_or_r, iu, iv, uu, vv)) {
                    continue;
                }
                if (sc_write_texel(map, iu, iv, value)) {
                    any = 1;
                }
            }
        }
    } else {
        int iv0 = (int)floor((fmin(v0, v1) - pad_v - map->origin_v) / cell_v);
        int iv1 = (int)floor((fmax(v0, v1) + pad_v - map->origin_v) / cell_v);
        int iv;
        if (iv0 < 0) {
            iv0 = 0;
        }
        if (iv1 > map->nv - 1) {
            iv1 = map->nv - 1;
        }
        if (iv0 > iv1) {
            return 0;
        }
        for (iu = iu0; iu <= iu1; iu++) {
            double uu = map->origin_u + ((double)iu + 0.5) * map->cell_u;
            for (iv = iv0; iv <= iv1; iv++) {
                double vv = map->origin_v + ((double)iv + 0.5) * map->cell_v;
                if (!sc_capsule_hit(uu, vv, u0, v0, u1, v1, radius, v_scale)) {
                    continue;
                }
                if (!sc_texel_allowed(allow, allow_u0, allow_v0, allow_rows, allow_cols, occ, z_or_r, iu, iv, uu, vv)) {
                    continue;
                }
                if (sc_write_texel(map, iu, iv, value)) {
                    any = 1;
                }
            }
        }
    }
    if (any && changed != NULL) {
        *changed = 1;
    }
    return any;
}

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
    int *changed) {
    int i;
    if (map == NULL || u0 == NULL || v0 == NULL || u1 == NULL || v1 == NULL || burn == NULL || nseg <= 0) {
        return 0;
    }
    for (i = 0; i < nseg; i++) {
        double zr = z_or_r != NULL ? z_or_r[i] : 0.0;
        if (!burn[i]) {
            continue;
        }
        /* An allow window belongs to one stamp. Ignore it on later segments. */
        sc_laser_stamp_one(
            map,
            u0[i],
            v0[i],
            u1[i],
            v1[i],
            burn[i],
            radius,
            i == 0 ? allow : NULL,
            allow_u0,
            allow_v0,
            allow_rows,
            allow_cols,
            occ,
            zr,
            changed);
    }
    return 0;
}

int sc_laser_clear_capsules(
    ScLaserDecal *map,
    const double *u0,
    const double *v0,
    const double *u1,
    const double *v1,
    int nseg,
    double radius,
    int *changed) {
    int i;
    if (map == NULL || u0 == NULL || v0 == NULL || u1 == NULL || v1 == NULL || nseg <= 0) {
        return 0;
    }
    for (i = 0; i < nseg; i++) {
        sc_laser_stamp_one(map, u0[i], v0[i], u1[i], v1[i], 0, radius, NULL, 0, 0, 0, 0, NULL, 0.0, changed);
    }
    return 0;
}

static void sc_texel_range(double edge0, double edge1, double origin, double cell, int n, int *lo, int *hi) {
    double c = cell > 1e-12 ? cell : 1e-12;
    int a = (int)floor((edge0 - origin) / c);
    int b = (int)floor((edge1 - 1e-9 - origin) / c);
    if (a < 0) {
        a = 0;
    }
    if (b > n - 1) {
        b = n - 1;
    }
    *lo = a;
    *hi = b;
}

static int sc_in_bin(double center, double origin, double size, int index) {
    double step = size > 1e-12 ? size : 1e-12;
    return (int)floor((center - origin) / step) == index;
}

static int sc_theta_bin(double center, double origin, double size, double period, int nbin) {
    double step = size > 1e-12 ? size : 1e-12;
    double vv;
    int cj;
    if (period <= 0.0) {
        period = 360.0;
    }
    vv = sc_py_mod(center - origin, period) + origin;
    cj = (int)floor((vv - origin) / step);
    return sc_mod_int(cj, nbin);
}

static void sc_clear_at(ScLaserDecal *laser, int iu, int iv, int *changed) {
    uint8_t *p;
    if (iu < 0 || iv < 0 || iu >= laser->nx || iv >= laser->nv) {
        return;
    }
    p = &laser->intensity[(size_t)iu * (size_t)laser->nv + (size_t)iv];
    if (!*p) {
        return;
    }
    *p = 0;
    if (changed != NULL) {
        *changed = 1;
    }
}

void sc_laser_clear_coarse_cell(
    ScLaserDecal *laser,
    int ix,
    int coarse_iv,
    double coarse_origin_u,
    double coarse_origin_v,
    double coarse_du,
    double coarse_dv,
    int coarse_nv,
    int *changed) {
    double u0;
    double u1;
    double cell_u;
    int lu0;
    int lu1;
    int iu;
    if (laser == NULL || laser->intensity == NULL || laser->nx <= 0 || laser->nv <= 0) {
        return;
    }
    if (coarse_du <= 0.0 || coarse_dv <= 0.0) {
        return;
    }
    cell_u = laser->cell_u > 1e-12 ? laser->cell_u : 1e-12;
    u0 = coarse_origin_u + (double)ix * coarse_du;
    u1 = u0 + coarse_du;
    sc_texel_range(u0, u1, laser->origin_u, cell_u, laser->nx, &lu0, &lu1);
    if (lu0 > lu1) {
        return;
    }
    if (!laser->wrap_v) {
        double v0 = coarse_origin_v + (double)coarse_iv * coarse_dv;
        double v1 = v0 + coarse_dv;
        int lv0;
        int lv1;
        int iv;
        sc_texel_range(v0, v1, laser->origin_v, laser->cell_v, laser->nv, &lv0, &lv1);
        if (lv0 > lv1) {
            return;
        }
        for (iu = lu0; iu <= lu1; iu++) {
            double cu = laser->origin_u + ((double)iu + 0.5) * laser->cell_u;
            if (!sc_in_bin(cu, coarse_origin_u, coarse_du, ix)) {
                continue;
            }
            for (iv = lv0; iv <= lv1; iv++) {
                double cv = laser->origin_v + ((double)iv + 0.5) * laser->cell_v;
                if (!sc_in_bin(cv, coarse_origin_v, coarse_dv, coarse_iv)) {
                    continue;
                }
                sc_clear_at(laser, iu, iv, changed);
            }
        }
        return;
    }
    {
        double period = laser->v_period > 0.0 ? laser->v_period : 360.0;
        double cell_v = laser->cell_v > 1e-12 ? laser->cell_v : 1e-12;
        double th0 = coarse_origin_v + (double)coarse_iv * coarse_dv;
        double th1 = th0 + coarse_dv;
        int bins = coarse_nv > 0 ? coarse_nv : 1;
        int lo = (int)floor((th0 - laser->origin_v) / cell_v - 0.5) - 2;
        int hi = (int)floor((th1 - laser->origin_v) / cell_v - 0.5) + 2;
        int direct;
        int i;
        if (hi < lo) {
            return;
        }
        direct = (hi - lo) > laser->nv + 4;
        if (direct) {
            lo = 0;
            hi = laser->nv - 1;
        }
        for (iu = lu0; iu <= lu1; iu++) {
            double cu = laser->origin_u + ((double)iu + 0.5) * laser->cell_u;
            if (!sc_in_bin(cu, coarse_origin_u, coarse_du, ix)) {
                continue;
            }
            for (i = lo; i <= hi; i++) {
                int iv = direct ? i : sc_mod_int(i, laser->nv);
                double cv = laser->origin_v + ((double)iv + 0.5) * laser->cell_v;
                if (sc_theta_bin(cv, coarse_origin_v, coarse_dv, period, bins) != coarse_iv) {
                    continue;
                }
                sc_clear_at(laser, iu, iv, changed);
            }
        }
    }
}
