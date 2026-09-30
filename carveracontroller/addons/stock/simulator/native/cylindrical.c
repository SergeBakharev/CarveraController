/* Cylindrical / rotary stock: leftover radius at each (X, angle) cell.
 *
 * A cell is a ray from the rotation axis. Carving shrinks that leftover radius.
 * The A axis spins the stock (or equivalently, we spin the tool into stock space).
 */
#include "stock_carve_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SC_MAX_SLOTS 64 /* max cylinder/cone pieces we keep from one tool profile */

typedef struct ScSlot {
    double lo, hi; /* leftover-radius interval where this flute piece hits */
    int ok;
} ScSlot;

/* Same right-hand YZ spin as sc_rotate_yz, but cos/sin are precomputed. */
static void sc_rotate_yz_cs(double y, double z, double c, double s, double *oy, double *oz) {
    *oy = y * c - z * s;
    *oz = y * s + z * c;
}

/* cos/sin of -angle_deg, matching sc_rotate_yz(angle_deg) callers that pass -A. */
static void sc_pose_cs(double angle_deg, double *c, double *s) {
    double rad = -angle_deg * (M_PI / 180.0);
    *c = cos(rad);
    *s = sin(rad);
}

static int sc_x_index(double x, double min_x, double cell) {
    return (int)floor((x - min_x) / cell);
}

static int sc_theta_index(double angle_deg, double d_theta, int n_theta) {
    double a = sc_py_mod(angle_deg, 360.0);
    int i = (int)(a / d_theta);
    if (i < 0) {
        i = 0;
    }
    if (n_theta <= 0) {
        return 0;
    }
    return i % n_theta;
}

/* Angle of a world point on the unwrapped cylinder, at this A pose. */
static double sc_stock_theta_cs(
    double y,
    double z,
    double angle,
    double axis_y,
    double axis_z,
    double ca,
    double sa) {
    double y_axis, z_axis;
    sc_rotate_yz_cs(axis_y, axis_z, ca, sa, &y_axis, &z_axis);
    return atan2(y - y_axis, z - z_axis) * (180.0 / M_PI) - angle;
}

/* Angle bins covering [a_start, a_end], wrapping at 360°. */
static int sc_theta_indices(double a_start, double a_end, double d_theta, int n_theta, int *out) {
    double span = a_end - a_start;
    int i0, n, i, count;
    if (span < 0.0) {
        double tmp = a_start;
        a_start = a_end;
        a_end = tmp;
        span = -span;
    }
    if (span >= 360.0 - 1e-6) {
        for (i = 0; i < n_theta; i++) {
            out[i] = i;
        }
        return n_theta;
    }
    i0 = sc_theta_index(a_start, d_theta, n_theta);
    n = (int)ceil(span / d_theta) + 2;
    if (n + 1 >= n_theta) {
        for (i = 0; i < n_theta; i++) {
            out[i] = i;
        }
        return n_theta;
    }
    count = n + 1;
    for (i = 0; i < count; i++) {
        out[i] = (i0 + i) % n_theta;
    }
    return count;
}

/* Which angle bins the tool can reach at this pose.
 * If the path almost hits the axis, every bin is in range.
 */
static int sc_theta_window(
    double p0y,
    double p0z,
    double p1y,
    double p1z,
    double angle,
    double max_r,
    double cell,
    double d_theta,
    int n_theta,
    double axis_y,
    double axis_z,
    int *out) {
    double y_axis, z_axis, dy0, dz0, dy1, dz1, vx, vz, len_sq, min_dist, reach;
    double th0, th1, delta, lo, hi, pad;
    double ca, sa;
    int i;
    sc_pose_cs(angle, &ca, &sa);
    sc_rotate_yz_cs(axis_y, axis_z, ca, sa, &y_axis, &z_axis);
    dy0 = p0y - y_axis;
    dz0 = p0z - z_axis;
    dy1 = p1y - y_axis;
    dz1 = p1z - z_axis;
    vx = dy1 - dy0;
    vz = dz1 - dz0;
    len_sq = vx * vx + vz * vz;
    if (len_sq < 1e-18) {
        min_dist = hypot(dy0, dz0);
    } else {
        double t = sc_clamp(-(dy0 * vx + dz0 * vz) / len_sq, 0.0, 1.0);
        min_dist = hypot(dy0 + t * vx, dz0 + t * vz);
    }
    reach = max_r + cell;
    if (min_dist < reach + 1e-9) {
        for (i = 0; i < n_theta; i++) {
            out[i] = i;
        }
        return n_theta;
    }
    pad = asin(fmin(1.0, reach / min_dist)) * (180.0 / M_PI) + d_theta;
    th0 = sc_stock_theta_cs(p0y, p0z, angle, axis_y, axis_z, ca, sa);
    th1 = sc_stock_theta_cs(p1y, p1z, angle, axis_y, axis_z, ca, sa);
    delta = sc_py_mod(th1 - th0 + 180.0, 360.0) - 180.0;
    lo = fmin(th0, th0 + delta) - pad;
    hi = fmax(th0, th0 + delta) + pad;
    return sc_theta_indices(lo, hi, d_theta, n_theta, out);
}

/* Where a ray from the axis (s = leftover radius) hits a constant-radius flute.
 * Returns the enter/exit s interval, or invalid if they miss.
 */
static void sc_cylinder_interval(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double tx,
    double ty,
    double tz,
    double radius,
    double flute_z0,
    double flute_z1,
    double *s_enter,
    double *s_exit,
    int *valid) {
    double z_lo = tz + flute_z0;
    double z_hi = tz + flute_z1;
    double dx, bud, q, disc, uy_safe, s_a, s_b, s_xy_lo, s_xy_hi;
    double uz_safe, sz_a, sz_b, s_z_lo, s_z_hi;
    int u_fixed, z_fixed;
    if (z_hi < z_lo) {
        double tmp = z_lo;
        z_lo = z_hi;
        z_hi = tmp;
    }
    dx = wx - tx;
    bud = radius * radius - dx * dx;
    q = y0 - ty;
    u_fixed = fabs(uy) < 1e-12;
    disc = sqrt(fmax(bud, 0.0));
    uy_safe = u_fixed ? 1.0 : uy;
    s_a = (-q - disc) / uy_safe;
    s_b = (-q + disc) / uy_safe;
    s_xy_lo = fmin(s_a, s_b);
    s_xy_hi = fmax(s_a, s_b);
    if (bud < -1e-12) {
        s_xy_lo = SC_INF;
        s_xy_hi = -SC_INF;
    }
    if (u_fixed) {
        if (q * q <= bud + 1e-12) {
            s_xy_lo = -SC_INF;
            s_xy_hi = SC_INF;
        } else {
            s_xy_lo = SC_INF;
            s_xy_hi = -SC_INF;
        }
    }
    z_fixed = fabs(uz) < 1e-12;
    uz_safe = z_fixed ? 1.0 : uz;
    sz_a = (z_lo - z0_axis) / uz_safe;
    sz_b = (z_hi - z0_axis) / uz_safe;
    s_z_lo = fmin(sz_a, sz_b);
    s_z_hi = fmax(sz_a, sz_b);
    if (z_fixed) {
        if ((z_lo - 1e-9) <= z0_axis && z0_axis <= (z_hi + 1e-9)) {
            s_z_lo = -SC_INF;
            s_z_hi = SC_INF;
        } else {
            s_z_lo = SC_INF;
            s_z_hi = -SC_INF;
        }
    }
    *s_enter = fmax(fmax(s_xy_lo, s_z_lo), 0.0);
    *s_exit = fmin(s_xy_hi, s_z_hi);
    *valid = *s_enter <= *s_exit + 1e-9;
}

/* If leftover radius (or just inside it) sits in the interval, cut back to enter. */
static void sc_hit_from_s(double s_enter, double s_exit, int valid, double s_hi, double probe, double *new_s, int *hit) {
    double s_probe = fmax(s_hi - probe, 0.0);
    int inside_hi = valid && s_hi >= s_enter - 1e-9 && s_hi <= s_exit + 1e-9;
    int inside_pr = valid && s_probe >= s_enter - 1e-9 && s_probe <= s_exit + 1e-9;
    *hit = s_hi >= 0.0 && (inside_hi || inside_pr);
    *new_s = *hit ? s_enter : s_hi;
}

/* Expand an s-interval accumulator (convex union → bounding interval). */
static void sc_s_union(double lo, double hi, int ok, double *acc_lo, double *acc_hi, int *any) {
    if (!ok || lo > hi + 1e-9) {
        return;
    }
    if (!*any) {
        *acc_lo = lo;
        *acc_hi = hi;
        *any = 1;
        return;
    }
    if (lo < *acc_lo) {
        *acc_lo = lo;
    }
    if (hi > *acc_hi) {
        *acc_hi = hi;
    }
}

/* Ray (wx, y0+s*uy) within R of a disk at (cx, cy) → s interval. */
static void sc_ray_disk_s(
    double wx,
    double y0,
    double uy,
    double cx,
    double cy,
    double R,
    double *s_lo,
    double *s_hi,
    int *ok) {
    double ax = wx - cx;
    double q = y0 - cy;
    double bud = R * R - ax * ax;
    int u_fixed = fabs(uy) < 1e-12;
    double disc, s_a, s_b;
    if (bud < -1e-12) {
        *ok = 0;
        return;
    }
    if (u_fixed) {
        if (q * q <= bud + 1e-12) {
            *s_lo = -SC_INF;
            *s_hi = SC_INF;
            *ok = 1;
        } else {
            *ok = 0;
        }
        return;
    }
    disc = sqrt(fmax(bud, 0.0));
    s_a = (-q - disc) / uy;
    s_b = (-q + disc) / uy;
    *s_lo = fmin(s_a, s_b);
    *s_hi = fmax(s_a, s_b);
    *ok = 1;
}

/* Ray (wx, y0+s*uy) within R of XY segment p0→p1 (stadium ∩ ray). */
static void sc_ray_stadium_s(
    double wx,
    double y0,
    double uy,
    double p0x,
    double p0y,
    double p1x,
    double p1y,
    double R,
    double *s_lo,
    double *s_hi,
    int *ok) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double L2 = dx * dx + dy * dy;
    double acc_lo = SC_INF, acc_hi = -SC_INF;
    int any = 0;
    double d_lo, d_hi;
    int d_ok;

    sc_ray_disk_s(wx, y0, uy, p0x, p0y, R, &d_lo, &d_hi, &d_ok);
    sc_s_union(d_lo, d_hi, d_ok, &acc_lo, &acc_hi, &any);
    if (L2 >= 1e-18) {
        double g0, g1, lim, line_lo, line_hi, alpha, beta, t_lo, t_hi, strip_lo, strip_hi;
        int line_ok = 1;
        sc_ray_disk_s(wx, y0, uy, p1x, p1y, R, &d_lo, &d_hi, &d_ok);
        sc_s_union(d_lo, d_hi, d_ok, &acc_lo, &acc_hi, &any);

        /* Infinite strip around the chord, then clamp to t in [0,1]. */
        g0 = (wx - p0x) * dy - (y0 - p0y) * dx;
        g1 = uy * dx; /* cross = g0 - s*g1 */
        lim = R * sqrt(L2);
        if (fabs(g1) < 1e-12) {
            if (fabs(g0) > lim + 1e-12) {
                line_ok = 0;
            } else {
                line_lo = -SC_INF;
                line_hi = SC_INF;
            }
        } else {
            double s_a = (g0 - lim) / g1;
            double s_b = (g0 + lim) / g1;
            line_lo = fmin(s_a, s_b);
            line_hi = fmax(s_a, s_b);
        }
        alpha = (wx - p0x) * dx + (y0 - p0y) * dy;
        beta = uy * dy;
        if (fabs(beta) < 1e-12) {
            if (alpha < -1e-12 || alpha > L2 + 1e-12) {
                line_ok = 0;
            } else {
                t_lo = -SC_INF;
                t_hi = SC_INF;
            }
        } else if (beta > 0.0) {
            t_lo = (0.0 - alpha) / beta;
            t_hi = (L2 - alpha) / beta;
        } else {
            t_lo = (L2 - alpha) / beta;
            t_hi = (0.0 - alpha) / beta;
        }
        if (line_ok) {
            strip_lo = fmax(line_lo, t_lo);
            strip_hi = fmin(line_hi, t_hi);
            sc_s_union(strip_lo, strip_hi, strip_lo <= strip_hi + 1e-9, &acc_lo, &acc_hi, &any);
        }
    }
    *ok = any;
    *s_lo = acc_lo;
    *s_hi = acc_hi;
}

/* Const-r tool sweeping p0→p1: leftover-radius interval along a stock ray.
 * Matches sc_point_inside_tool for horizontal and plunge moves; callers keep
 * binary search when tip Z also changes with XY (coupled t window).
 */
static void sc_swept_cylinder_interval(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double radius,
    double flute_z0,
    double flute_z1,
    double *s_enter,
    double *s_exit,
    int *valid) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double xy_len_sq = dx * dx + dy * dy;
    double z_lo = flute_z0;
    double z_hi = flute_z1;
    double s_xy_lo, s_xy_hi, s_z_lo, s_z_hi;
    int xy_ok, z_ok;
    if (z_hi < z_lo) {
        double tmp = z_lo;
        z_lo = z_hi;
        z_hi = tmp;
    }
    if (radius <= 0.0) {
        *valid = 0;
        return;
    }
    if (xy_len_sq < 1e-18) {
        /* Pure plunge: fixed XY, flute spans the tip Z travel. */
        double tip_lo = p0z < p1z ? p0z : p1z;
        double tip_hi = p0z > p1z ? p0z : p1z;
        sc_cylinder_interval(
            wx,
            uy,
            uz,
            y0,
            z0_axis,
            p0x,
            p0y,
            tip_lo,
            radius,
            z_lo,
            z_hi + (tip_hi - tip_lo),
            s_enter,
            s_exit,
            valid);
        return;
    }
    if (fabs(dz) >= 1e-12) {
        /* XY+Z coupled: leave to binary search in sc_cut_one. */
        *valid = 0;
        return;
    }
    /* Horizontal feed: XY stadium ∩ Z slab (tip Z fixed). */
    sc_ray_stadium_s(wx, y0, uy, p0x, p0y, p1x, p1y, radius, &s_xy_lo, &s_xy_hi, &xy_ok);
    {
        int z_fixed = fabs(uz) < 1e-12;
        double uz_safe = z_fixed ? 1.0 : uz;
        double world_z0 = p0z + z_lo;
        double world_z1 = p0z + z_hi;
        double sz_a = (world_z0 - z0_axis) / uz_safe;
        double sz_b = (world_z1 - z0_axis) / uz_safe;
        s_z_lo = fmin(sz_a, sz_b);
        s_z_hi = fmax(sz_a, sz_b);
        if (z_fixed) {
            if ((world_z0 - 1e-9) <= z0_axis && z0_axis <= (world_z1 + 1e-9)) {
                s_z_lo = -SC_INF;
                s_z_hi = SC_INF;
                z_ok = 1;
            } else {
                z_ok = 0;
            }
        } else {
            z_ok = 1;
        }
    }
    if (!xy_ok || !z_ok) {
        *valid = 0;
        return;
    }
    *s_enter = fmax(fmax(s_xy_lo, s_z_lo), 0.0);
    *s_exit = fmin(s_xy_hi, s_z_hi);
    *valid = *s_enter <= *s_exit + 1e-9;
}

/* Same as sc_cylinder_interval but the flute tapers (cone / V-bit).
 * A taper can produce two separate hit intervals.
 */
static void sc_frustum_slots(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double tx,
    double ty,
    double tz,
    double za,
    double zb,
    double ra,
    double rb,
    double *lo1,
    double *hi1,
    int *ok1,
    double *lo2,
    double *hi2,
    int *ok2) {
    double dx = wx - tx;
    double q = y0 - ty;
    double z_lo = tz + za;
    double z_hi = tz + zb;
    double dz = zb - za;
    double k = fabs(dz) < 1e-12 ? 0.0 : (rb - ra) / dz;
    double A = ra + k * (z0_axis - tz - za);
    double B = k * uz;
    int z_fixed = fabs(uz) < 1e-12;
    int inside_z = (z_lo - 1e-9) <= z0_axis && z0_axis <= (z_hi + 1e-9);
    double uz_safe = z_fixed ? 1.0 : uz;
    double sz_a = (z_lo - z0_axis) / uz_safe;
    double sz_b = (z_hi - z0_axis) / uz_safe;
    double s_z_lo = fmin(sz_a, sz_b);
    double s_z_hi = fmax(sz_a, sz_b);
    int b_fixed, r_pos_fixed, box_ok, lin, always_in, up, down, v1, v2, both, c1_fixed, l_ok;
    double B_safe, s_r0, s_r_lo, s_r_hi, box_lo, box_hi;
    double cs2, cs1, cs0, disc_raw, disc, sqrt_d, cs2_safe, inv, r1, r2, root_lo, root_hi;
    double u_lo, u_hi, w1_lo, w1_hi, w2_lo, w2_hi;
    double cs1_safe, s_lin, s_lin_lo, s_lin_hi, l_lo, l_hi;
    if (z_fixed) {
        if (inside_z) {
            s_z_lo = -SC_INF;
            s_z_hi = SC_INF;
        } else {
            s_z_lo = SC_INF;
            s_z_hi = -SC_INF;
        }
    }
    b_fixed = fabs(B) < 1e-12;
    r_pos_fixed = A >= -1e-12;
    B_safe = b_fixed ? 1.0 : B;
    s_r0 = -A / B_safe;
    if (b_fixed) {
        if (r_pos_fixed) {
            s_r_lo = -SC_INF;
            s_r_hi = SC_INF;
        } else {
            s_r_lo = SC_INF;
            s_r_hi = -SC_INF;
        }
    } else if (B > 0.0) {
        s_r_lo = s_r0;
        s_r_hi = SC_INF;
    } else {
        s_r_lo = -SC_INF;
        s_r_hi = s_r0;
    }
    box_lo = fmax(fmax(s_z_lo, s_r_lo), 0.0);
    box_hi = fmin(s_z_hi, s_r_hi);
    box_ok = box_lo <= box_hi + 1e-9;
    cs2 = uy * uy - B * B;
    cs1 = 2.0 * q * uy - 2.0 * A * B;
    cs0 = dx * dx + q * q - A * A;
    lin = fabs(cs2) < 1e-14;
    disc_raw = cs1 * cs1 - 4.0 * cs2 * cs0;
    disc = fmax(disc_raw, 0.0);
    sqrt_d = sqrt(disc);
    cs2_safe = lin ? 1.0 : cs2;
    inv = 0.5 / cs2_safe;
    r1 = (-cs1 - sqrt_d) * inv;
    r2 = (-cs1 + sqrt_d) * inv;
    root_lo = fmin(r1, r2);
    root_hi = fmax(r1, r2);
    *lo1 = SC_INF;
    *hi1 = -SC_INF;
    *lo2 = SC_INF;
    *hi2 = -SC_INF;
    always_in = !lin && disc_raw < -1e-12 && cs2 < 0.0 && box_ok;
    if (always_in) {
        *lo1 = box_lo;
        *hi1 = box_hi;
    }
    up = !lin && cs2 >= 0.0 && disc_raw >= -1e-12 && box_ok;
    u_lo = fmax(box_lo, root_lo);
    u_hi = fmin(box_hi, root_hi);
    if (up && u_lo <= u_hi + 1e-9) {
        *lo1 = u_lo;
        *hi1 = u_hi;
    }
    down = !lin && cs2 < 0.0 && disc_raw >= -1e-12 && box_ok;
    w1_lo = box_lo;
    w1_hi = fmin(box_hi, root_lo);
    w2_lo = fmax(box_lo, root_hi);
    w2_hi = box_hi;
    v1 = down && w1_lo <= w1_hi + 1e-9;
    v2 = down && w2_lo <= w2_hi + 1e-9;
    both = v1 && v2;
    if (v1) {
        *lo1 = w1_lo;
        *hi1 = w1_hi;
    }
    if (!v1 && v2) {
        *lo1 = w2_lo;
        *hi1 = w2_hi;
    }
    if (both) {
        *lo2 = w2_lo;
        *hi2 = w2_hi;
    }
    c1_fixed = fabs(cs1) < 1e-14;
    cs1_safe = c1_fixed ? 1.0 : cs1;
    s_lin = -cs0 / cs1_safe;
    if (c1_fixed) {
        if (cs0 <= 1e-12) {
            s_lin_lo = -SC_INF;
            s_lin_hi = SC_INF;
        } else {
            s_lin_lo = SC_INF;
            s_lin_hi = -SC_INF;
        }
    } else if (cs1 > 0.0) {
        s_lin_lo = -SC_INF;
        s_lin_hi = s_lin;
    } else {
        s_lin_lo = s_lin;
        s_lin_hi = SC_INF;
    }
    l_lo = fmax(box_lo, s_lin_lo);
    l_hi = fmin(box_hi, s_lin_hi);
    l_ok = lin && box_ok && l_lo <= l_hi + 1e-9;
    if (l_ok) {
        *lo1 = l_lo;
        *hi1 = l_hi;
    }
    *ok1 = *lo1 <= *hi1 + 1e-9;
    *ok2 = *lo2 <= *hi2 + 1e-9;
}

/* Walk the tool profile: each pair of samples is a cylinder or a cone. */
static int sc_collect_slots(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double tx,
    double ty,
    double tz,
    const ScProfile *profile,
    ScSlot *slots) {
    int nslots = 0;
    int i;
    for (i = 0; i < profile->n - 1 && nslots < SC_MAX_SLOTS; i++) {
        double za = profile->zs[i];
        double zb = profile->zs[i + 1];
        double ra = profile->rs[i];
        double rb = profile->rs[i + 1];
        double lo, hi, lo2, hi2;
        int ok, ok2;
        if (fabs(zb - za) < 1e-12 && fabs(rb - ra) < 1e-12) {
            continue;
        }
        if (zb < za) {
            double tzp = za, tr = ra;
            za = zb;
            zb = tzp;
            ra = rb;
            rb = tr;
        }
        if (fabs(rb - ra) < 1e-12) {
            sc_cylinder_interval(wx, uy, uz, y0, z0_axis, tx, ty, tz, ra, za, zb, &lo, &hi, &ok);
            slots[nslots].lo = lo;
            slots[nslots].hi = hi;
            slots[nslots].ok = ok;
            nslots++;
            continue;
        }
        sc_frustum_slots(wx, uy, uz, y0, z0_axis, tx, ty, tz, za, zb, ra, rb, &lo, &hi, &ok, &lo2, &hi2, &ok2);
        slots[nslots].lo = lo;
        slots[nslots].hi = hi;
        slots[nslots].ok = ok;
        nslots++;
        if (ok2 && nslots < SC_MAX_SLOTS) {
            slots[nslots].lo = lo2;
            slots[nslots].hi = hi2;
            slots[nslots].ok = 1;
            nslots++;
        }
    }
    return nslots;
}

/* Analytic cut: if leftover radius is inside any flute interval, shrink it to
 * the earliest enter. Overlapping pieces of the flute are merged first.
 */
static void sc_revolution_cut(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double tx,
    double ty,
    double tz,
    const ScProfile *profile,
    double s_hi,
    double probe,
    double *new_s,
    int *hit) {
    ScSlot slots[SC_MAX_SLOTS];
    int nslots, i, pass, any;
    double enter, exit_, s_probe;
    nslots = sc_collect_slots(wx, uy, uz, y0, z0_axis, tx, ty, tz, profile, slots);
    if (nslots <= 0) {
        *new_s = s_hi;
        *hit = 0;
        return;
    }
    if (nslots == 1 && profile->n >= 2) {
        /* Fast path when the tool is a single cylinder. */
        int single_cyl = 1;
        int segs = 0;
        for (i = 0; i < profile->n - 1; i++) {
            if (fabs(profile->zs[i + 1] - profile->zs[i]) < 1e-12 && fabs(profile->rs[i + 1] - profile->rs[i]) < 1e-12) {
                continue;
            }
            segs++;
            if (fabs(profile->rs[i + 1] - profile->rs[i]) >= 1e-12) {
                single_cyl = 0;
            }
        }
        if (segs == 1 && single_cyl) {
            sc_hit_from_s(slots[0].lo, slots[0].hi, slots[0].ok, s_hi, probe, new_s, hit);
            return;
        }
    }
    if (nslots == 1) {
        sc_hit_from_s(slots[0].lo, slots[0].hi, slots[0].ok, s_hi, probe, new_s, hit);
        return;
    }
    s_probe = fmax(s_hi - probe, 0.0);
    any = 0;
    enter = SC_INF;
    exit_ = -SC_INF;
    for (i = 0; i < nslots; i++) {
        int contains;
        if (!slots[i].ok) {
            continue;
        }
        contains = (s_hi >= slots[i].lo - 1e-9 && s_hi <= slots[i].hi + 1e-9) ||
            (s_probe >= slots[i].lo - 1e-9 && s_probe <= slots[i].hi + 1e-9);
        if (!contains) {
            continue;
        }
        any = 1;
        if (slots[i].lo < enter) {
            enter = slots[i].lo;
        }
        if (slots[i].hi > exit_) {
            exit_ = slots[i].hi;
        }
    }
    *hit = any && s_hi >= 0.0;
    if (!*hit) {
        *new_s = s_hi;
        return;
    }
    for (pass = 0; pass < nslots - 1; pass++) {
        double nenter = enter;
        double nexit = exit_;
        for (i = 0; i < nslots; i++) {
            int overlap;
            if (!slots[i].ok) {
                continue;
            }
            overlap = slots[i].lo <= exit_ + 1e-9 && slots[i].hi >= enter - 1e-9;
            if (!overlap) {
                continue;
            }
            if (slots[i].lo < nenter) {
                nenter = slots[i].lo;
            }
            if (slots[i].hi > nexit) {
                nexit = slots[i].hi;
            }
        }
        enter = nenter;
        exit_ = nexit;
    }
    *new_s = fmax(enter, 0.0);
}

/* How many binary-search steps to land within about one cell. */
static int sc_radius_iters(double cell, double stock_radius) {
    double step = fmax(cell * 0.02, 1e-5);
    double ratio = fmax(stock_radius, cell) / step;
    int n = (int)ceil(log2(ratio)) + 1;
    if (n < 8) {
        n = 8;
    }
    if (n > 14) {
        n = 14;
    }
    return n;
}

/* Short moves: closed-form cylinder/cone hit.
 * Long const-r horizontal/plunge: swept-cylinder interval.
 * Long ball/V (or const-r with coupled ΔZ): binary-search leftover radius.
 */
static void sc_cut_one(
    double wx,
    double uy,
    double uz,
    double y0,
    double z0_axis,
    double s_hi,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double cell,
    double stock_radius,
    const ScProfile *profile,
    double *new_s,
    int *hit) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double seg_len_sq = dx * dx + dy * dy + dz * dz;
    double z0 = profile->n ? profile->zs[0] : 0.0;
    double z1 = profile->n ? profile->zs[profile->n - 1] : 0.0;
    double probe = cell * 0.5;
    if (seg_len_sq <= cell * cell) {
        double tx, ty, tz;
        if (seg_len_sq < 1e-18) {
            tx = p0x;
            ty = p0y;
            tz = p0z;
        } else {
            tx = p0x + 0.5 * dx;
            ty = p0y + 0.5 * dy;
            tz = p0z + 0.5 * dz;
        }
        if (profile->const_r >= 0.0) {
            double enter, exit_;
            int valid;
            sc_cylinder_interval(
                wx, uy, uz, y0, z0_axis, tx, ty, tz, profile->const_r, z0, z1, &enter, &exit_, &valid);
            sc_hit_from_s(enter, exit_, valid, s_hi, probe, new_s, hit);
            return;
        }
        sc_revolution_cut(wx, uy, uz, y0, z0_axis, tx, ty, tz, profile, s_hi, probe, new_s, hit);
        return;
    }
    if (profile->const_r >= 0.0) {
        double xy_len_sq = dx * dx + dy * dy;
        /* Swept closed form when tip Z is fixed or the move is a pure plunge. */
        if (xy_len_sq < 1e-18 || fabs(dz) < 1e-12) {
            double enter, exit_;
            int valid;
            sc_swept_cylinder_interval(
                wx,
                uy,
                uz,
                y0,
                z0_axis,
                p0x,
                p0y,
                p0z,
                p1x,
                p1y,
                p1z,
                profile->const_r,
                z0,
                z1,
                &enter,
                &exit_,
                &valid);
            sc_hit_from_s(enter, exit_, valid, s_hi, probe, new_s, hit);
            return;
        }
    }
    {
        int iters, k;
        double lo, hi;
        /* Probe a leftover radius: convert it to a world point, then test the swept tool. */
        #define SC_INSIDE_R(r_field, dest)                                                          \
            do {                                                                                    \
                double _r = (r_field);                                                              \
                if (_r < 0.0) {                                                                     \
                    dest = 0;                                                                       \
                } else {                                                                            \
                    double _yy = y0 + _r * uy;                                                      \
                    double _zz = z0_axis + _r * uz;                                                 \
                    dest = sc_point_inside_tool(wx, _yy, _zz, p0x, p0y, p0z, p1x, p1y, p1z, profile); \
                }                                                                                   \
            } while (0)
        int hit_s = 0, hit_p = 0;
        SC_INSIDE_R(s_hi, hit_s);
        SC_INSIDE_R(fmax(s_hi - probe, 0.0), hit_p);
        *hit = hit_s || hit_p;
        if (!*hit) {
            *new_s = s_hi;
            return;
        }
        lo = 0.0;
        hi = s_hi;
        iters = sc_radius_iters(cell, stock_radius);
        for (k = 0; k < iters; k++) {
            double mid = 0.5 * (lo + hi);
            int ins = 0;
            SC_INSIDE_R(mid, ins);
            if (ins) {
                hi = mid;
            } else {
                lo = mid;
            }
        }
        *new_s = fmax(lo, 0.0);
        #undef SC_INSIDE_R
    }
}

static int sc_cmp_double(const void *a, const void *b) {
    double da = *(const double *)a;
    double db = *(const double *)b;
    if (da < db) {
        return -1;
    }
    if (da > db) {
        return 1;
    }
    return 0;
}

/* Sample times along the move at every X-cell and A-bin the tool crosses.
 * Without this, a long move could skip a grid line.
 */
static int sc_pose_ts(
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1,
    double min_x,
    double cell,
    double d_theta,
    double **out_ts,
    int *n_out) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double da = a1 - a0;
    double xyz_len = sqrt(dx * dx + dy * dy + dz * dz);
    double *ts = NULL;
    int n = 0, cap = 0, i, w;
    if (xyz_len < 1e-12 && fabs(da) < 1e-9) {
        ts = (double *)malloc(sizeof(double));
        if (ts == NULL) {
            return -1;
        }
        ts[0] = 0.0;
        *out_ts = ts;
        *n_out = 1;
        return 0;
    }
    cap = 16;
    ts = (double *)malloc((size_t)cap * sizeof(double));
    if (ts == NULL) {
        return -1;
    }
    ts[n++] = 0.0;
    ts[n++] = 1.0;
    if (fabs(dx) >= 1e-12) {
        double lo = dx > 0.0 ? p0x : p1x;
        double hi = dx > 0.0 ? p1x : p0x;
        double ix0d = ceil((lo - min_x) / cell - 0.5);
        double ix1d = floor((hi - min_x) / cell - 0.5);
        long ix;
        if (ix1d >= ix0d) {
            for (ix = (long)ix0d; (double)ix <= ix1d; ix++) {
                double wx = min_x + ((double)ix + 0.5) * cell;
                double t = (wx - p0x) / dx;
                if (n >= cap) {
                    double *grown;
                    cap *= 2;
                    grown = (double *)realloc(ts, (size_t)cap * sizeof(double));
                    if (grown == NULL) {
                        free(ts);
                        return -1;
                    }
                    ts = grown;
                }
                ts[n++] = t;
            }
        }
    }
    if (fabs(da) >= 1e-9) {
        double lo_a = da > 0.0 ? a0 : a1;
        double hi_a = da > 0.0 ? a1 : a0;
        double k0 = ceil(lo_a / d_theta - 0.5);
        double k1 = floor(hi_a / d_theta - 0.5);
        long k;
        if (k1 >= k0) {
            for (k = (long)k0; (double)k <= k1; k++) {
                double ac = ((double)k + 0.5) * d_theta;
                double t = (ac - a0) / da;
                if (n >= cap) {
                    double *grown;
                    cap *= 2;
                    grown = (double *)realloc(ts, (size_t)cap * sizeof(double));
                    if (grown == NULL) {
                        free(ts);
                        return -1;
                    }
                    ts = grown;
                }
                ts[n++] = t;
            }
        }
    }
    for (i = 0; i < n; i++) {
        double t = ts[i];
        if (t < 0.0) {
            t = 0.0;
        }
        if (t > 1.0) {
            t = 1.0;
        }
        ts[i] = round(t * 1e10) / 1e10;
    }
    qsort(ts, (size_t)n, sizeof(double), sc_cmp_double);
    w = 0;
    for (i = 0; i < n; i++) {
        if (w == 0 || ts[i] != ts[w - 1]) {
            ts[w++] = ts[i];
        }
    }
    if (w < 2) {
        ts[0] = 0.0;
        ts[1] = 1.0;
        w = 2;
    }
    *out_ts = ts;
    *n_out = w;
    return 0;
}

/* Mark mesh tiles for every (X row, angle bin) that actually changed. */
static void sc_mark_product(
    uint8_t *tile_mask,
    int ntt,
    int tile,
    const uint8_t *changed,
    int n_rows,
    int ix0,
    int n_theta,
    const int *it,
    int n_it) {
    int r, c;
    if (tile_mask == NULL || tile <= 0 || n_it <= 0) {
        return;
    }
    for (r = 0; r < n_rows; r++) {
        int row_hit = 0;
        for (c = 0; c < n_it; c++) {
            if (changed[r * n_it + c]) {
                row_hit = 1;
                break;
            }
        }
        if (!row_hit) {
            continue;
        }
        for (c = 0; c < n_it; c++) {
            int col_hit = 0;
            int rr;
            int tx, ty;
            for (rr = 0; rr < n_rows; rr++) {
                if (changed[rr * n_it + c]) {
                    col_hit = 1;
                    break;
                }
            }
            if (!col_hit) {
                continue;
            }
            tx = (r + ix0) / tile;
            ty = it[c] / tile;
            if (tx >= 0 && ty >= 0 && ty < ntt) {
                tile_mask[tx * ntt + ty] = 1;
            }
        }
    }
    (void)n_theta;
}

/* Apply sc_cut_one to a rectangle of (X, angle) cells at a fixed A pose. */
static int sc_apply_cut_window(
    float *radii,
    int n_theta,
    double *work,
    int ix0,
    int n_rows,
    const double *wx,
    const int *it,
    int n_it,
    double angle,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    const double *sin_t,
    const double *cos_t,
    double axis_y,
    double axis_z,
    double cell,
    double stock_radius,
    const ScProfile *profile,
    uint8_t *changed,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntt,
    int tile) {
    double y0, z0_axis;
    double *uy;
    double *uz;
    double ca, sa;
    int col, row, any = 0;
    sc_pose_cs(angle, &ca, &sa);
    sc_rotate_yz_cs(axis_y, axis_z, ca, sa, &y0, &z0_axis);
    uy = (double *)malloc((size_t)n_it * sizeof(double));
    uz = (double *)malloc((size_t)n_it * sizeof(double));
    if (uy == NULL || uz == NULL) {
        free(uy);
        free(uz);
        return -1;
    }
    for (col = 0; col < n_it; col++) {
        int ith = it[col];
        sc_rotate_yz_cs(sin_t[ith], cos_t[ith], ca, sa, &uy[col], &uz[col]);
    }
    for (row = 0; row < n_rows; row++) {
        for (col = 0; col < n_it; col++) {
            int ith = it[col];
            double s = work[row * n_theta + ith];
            double neu;
            int hit = 0;
            sc_cut_one(
                wx[row],
                uy[col],
                uz[col],
                y0,
                z0_axis,
                s,
                p0x,
                p0y,
                p0z,
                p1x,
                p1y,
                p1z,
                cell,
                stock_radius,
                profile,
                &neu,
                &hit);
            if (hit && neu < s - 1e-9) {
                work[row * n_theta + ith] = neu;
                if (changed != NULL) {
                    changed[row * n_it + col] = 1;
                }
                any = 1;
            }
        }
    }
    if (any) {
        for (row = 0; row < n_rows; row++) {
            int ix = ix0 + row;
            for (col = 0; col < n_it; col++) {
                int ith;
                if (changed != NULL && !changed[row * n_it + col]) {
                    continue;
                }
                ith = it[col];
                radii[ix * n_theta + ith] = (float)work[row * n_theta + ith];
                if (changed_mask != NULL) {
                    changed_mask[ix * n_theta + ith] = 1;
                }
            }
        }
        sc_mark_product(tile_mask, ntt, tile, changed, n_rows, ix0, n_theta, it, n_it);
    }
    free(uy);
    free(uz);
    return 0;
}

static int sc_copy_rows(const float *radii, int n_theta, int ix0, int n_rows, double *work) {
    int row, th;
    for (row = 0; row < n_rows; row++) {
        const float *src = radii + (size_t)(ix0 + row) * (size_t)n_theta;
        double *dst = work + (size_t)row * (size_t)n_theta;
        for (th = 0; th < n_theta; th++) {
            dst[th] = (double)src[th];
        }
    }
    return 0;
}

/* A barely moved - treat the tool as not spinning. */
static int sc_carve_constant(
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
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double angle,
    const ScProfile *profile,
    double *work,
    int *it,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntt) {
    double pad = profile->max_r + cell;
    int ix0 = sc_x_index(fmin(p0x, p1x) - pad, min_x, cell);
    int ix1 = sc_x_index(fmax(p0x, p1x) + pad, min_x, cell);
    int n_it, n_rows, row;
    uint8_t *changed;
    double *wx;
    if (ix0 < 0) {
        ix0 = 0;
    }
    if (ix1 > nx - 1) {
        ix1 = nx - 1;
    }
    if (ix0 > ix1) {
        return 0;
    }
    n_it = sc_theta_window(p0y, p0z, p1y, p1z, angle, profile->max_r, cell, d_theta, n_theta, axis_y, axis_z, it);
    if (n_it <= 0) {
        return 0;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(radii, n_theta, ix0, n_rows, work);
    wx = (double *)malloc((size_t)n_rows * sizeof(double));
    changed = (uint8_t *)calloc((size_t)n_rows * (size_t)n_it, 1);
    if (wx == NULL || changed == NULL) {
        free(wx);
        free(changed);
        return -1;
    }
    for (row = 0; row < n_rows; row++) {
        wx[row] = min_x + ((double)(ix0 + row) + 0.5) * cell;
    }
    if (sc_apply_cut_window(
            radii,
            n_theta,
            work,
            ix0,
            n_rows,
            wx,
            it,
            n_it,
            angle,
            p0x,
            p0y,
            p0z,
            p1x,
            p1y,
            p1z,
            sin_t,
            cos_t,
            axis_y,
            axis_z,
            cell,
            stock_radius,
            profile,
            changed,
            changed_mask,
            tile_mask,
            ntt,
            tile) != 0) {
        free(wx);
        free(changed);
        return -1;
    }
    free(wx);
    free(changed);
    return 0;
}

/* A spun a full turn in place: one cut radius applies to every angle at that X. */
static int sc_carve_full_rev(
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
    double tipx,
    double tipy,
    double tipz,
    double angle,
    const ScProfile *profile,
    double *work,
    int *it,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntt) {
    double pad = profile->max_r + cell;
    int ix0 = sc_x_index(tipx - pad, min_x, cell);
    int ix1 = sc_x_index(tipx + pad, min_x, cell);
    int n_it, n_rows, row, col;
    double y0, z0_axis;
    double ca, sa;
    double *uy, *uz, *wx, *r_cut;
    uint8_t *hit;
    uint8_t *upd;
    int *all_th;
    if (ix0 < 0) {
        ix0 = 0;
    }
    if (ix1 > nx - 1) {
        ix1 = nx - 1;
    }
    if (ix0 > ix1) {
        return 0;
    }
    n_it = sc_theta_window(tipy, tipz, tipy, tipz, angle, profile->max_r, cell, d_theta, n_theta, axis_y, axis_z, it);
    if (n_it <= 0) {
        return 0;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(radii, n_theta, ix0, n_rows, work);
    wx = (double *)malloc((size_t)n_rows * sizeof(double));
    r_cut = (double *)malloc((size_t)n_rows * sizeof(double));
    uy = (double *)malloc((size_t)n_it * sizeof(double));
    uz = (double *)malloc((size_t)n_it * sizeof(double));
    hit = (uint8_t *)calloc((size_t)n_rows * (size_t)n_it, 1);
    upd = (uint8_t *)calloc((size_t)n_rows * (size_t)n_theta, 1);
    all_th = (int *)malloc((size_t)n_theta * sizeof(int));
    if (!wx || !r_cut || !uy || !uz || !hit || !upd || !all_th) {
        free(wx);
        free(r_cut);
        free(uy);
        free(uz);
        free(hit);
        free(upd);
        free(all_th);
        return -1;
    }
    sc_pose_cs(angle, &ca, &sa);
    sc_rotate_yz_cs(axis_y, axis_z, ca, sa, &y0, &z0_axis);
    for (col = 0; col < n_it; col++) {
        sc_rotate_yz_cs(sin_t[it[col]], cos_t[it[col]], ca, sa, &uy[col], &uz[col]);
    }
    for (row = 0; row < n_rows; row++) {
        wx[row] = min_x + ((double)(ix0 + row) + 0.5) * cell;
        r_cut[row] = SC_INF;
    }
    for (row = 0; row < n_rows; row++) {
        for (col = 0; col < n_it; col++) {
            double s = work[row * n_theta + it[col]];
            double neu;
            int h = 0;
            sc_cut_one(
                wx[row], uy[col], uz[col], y0, z0_axis, s, tipx, tipy, tipz, tipx, tipy, tipz, cell, stock_radius, profile, &neu, &h);
            if (h) {
                hit[row * n_it + col] = 1;
                if (neu < r_cut[row]) {
                    r_cut[row] = neu;
                }
            }
        }
    }
    for (col = 0; col < n_theta; col++) {
        all_th[col] = col;
    }
    for (row = 0; row < n_rows; row++) {
        int any_hit = 0;
        for (col = 0; col < n_it; col++) {
            if (hit[row * n_it + col]) {
                any_hit = 1;
                break;
            }
        }
        if (!any_hit) {
            continue;
        }
        for (col = 0; col < n_theta; col++) {
            double s = work[row * n_theta + col];
            if (r_cut[row] < s - 1e-9) {
                work[row * n_theta + col] = r_cut[row];
                upd[row * n_theta + col] = 1;
                radii[(ix0 + row) * n_theta + col] = (float)r_cut[row];
                if (changed_mask != NULL) {
                    changed_mask[(ix0 + row) * n_theta + col] = 1;
                }
            }
        }
    }
    sc_mark_product(tile_mask, ntt, tile, upd, n_rows, ix0, n_theta, all_th, n_theta);
    free(wx);
    free(r_cut);
    free(uy);
    free(uz);
    free(hit);
    free(upd);
    free(all_th);
    return 0;
}

/* A changed a lot - stamp the tool at each sampled pose. */
static int sc_carve_moving(
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
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1,
    const ScProfile *profile,
    double *work,
    int *it,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntt) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double da = a1 - a0;
    double pad = profile->max_r + cell;
    int ix0 = sc_x_index(fmin(p0x, p1x) - pad, min_x, cell);
    int ix1 = sc_x_index(fmax(p0x, p1x) + pad, min_x, cell);
    int n_rows, si, row;
    double *ts = NULL;
    int n_ts = 0;
    double *wx_all;
    uint8_t *changed;
    int *all_th;
    if (ix0 < 0) {
        ix0 = 0;
    }
    if (ix1 > nx - 1) {
        ix1 = nx - 1;
    }
    if (ix0 > ix1) {
        return 0;
    }
    if (sc_pose_ts(p0x, p0y, p0z, p1x, p1y, p1z, a0, a1, min_x, cell, d_theta, &ts, &n_ts) != 0) {
        return -1;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(radii, n_theta, ix0, n_rows, work);
    wx_all = (double *)malloc((size_t)n_rows * sizeof(double));
    changed = (uint8_t *)calloc((size_t)n_rows * (size_t)n_theta, 1);
    all_th = (int *)malloc((size_t)n_theta * sizeof(int));
    if (!wx_all || !changed || !all_th) {
        free(ts);
        free(wx_all);
        free(changed);
        free(all_th);
        return -1;
    }
    for (row = 0; row < n_rows; row++) {
        wx_all[row] = min_x + ((double)(ix0 + row) + 0.5) * cell;
    }
    for (row = 0; row < n_theta; row++) {
        all_th[row] = row;
    }
    for (si = 0; si < n_ts; si++) {
        double t = ts[si];
        double tipx = p0x + t * dx;
        double tipy = p0y + t * dy;
        double tipz = p0z + t * dz;
        double ang = a0 + t * da;
        int n_it = sc_theta_window(tipy, tipz, tipy, tipz, ang, profile->max_r, cell, d_theta, n_theta, axis_y, axis_z, it);
        int j0, j1, sub_rows, col;
        double y0, z0_axis;
        double *uy, *uz;
        if (n_it <= 0) {
            continue;
        }
        j0 = sc_x_index(tipx - pad, min_x, cell) - ix0;
        j1 = sc_x_index(tipx + pad, min_x, cell) - ix0;
        if (j0 < 0) {
            j0 = 0;
        }
        if (j1 > n_rows - 1) {
            j1 = n_rows - 1;
        }
        if (j0 > j1) {
            continue;
        }
        sub_rows = j1 - j0 + 1;
        {
            double ca, sa;
            sc_pose_cs(ang, &ca, &sa);
            sc_rotate_yz_cs(axis_y, axis_z, ca, sa, &y0, &z0_axis);
            uy = (double *)malloc((size_t)n_it * sizeof(double));
            uz = (double *)malloc((size_t)n_it * sizeof(double));
            if (!uy || !uz) {
                free(uy);
                free(uz);
                free(ts);
                free(wx_all);
                free(changed);
                free(all_th);
                return -1;
            }
            for (col = 0; col < n_it; col++) {
                sc_rotate_yz_cs(sin_t[it[col]], cos_t[it[col]], ca, sa, &uy[col], &uz[col]);
            }
        }
        for (row = 0; row < sub_rows; row++) {
            int gr = j0 + row;
            for (col = 0; col < n_it; col++) {
                int ith = it[col];
                double s = work[gr * n_theta + ith];
                double neu;
                int hit = 0;
                sc_cut_one(
                    wx_all[gr],
                    uy[col],
                    uz[col],
                    y0,
                    z0_axis,
                    s,
                    tipx,
                    tipy,
                    tipz,
                    tipx,
                    tipy,
                    tipz,
                    cell,
                    stock_radius,
                    profile,
                    &neu,
                    &hit);
                if (hit && neu < s - 1e-9) {
                    work[gr * n_theta + ith] = neu;
                    changed[gr * n_theta + ith] = 1;
                }
            }
        }
        free(uy);
        free(uz);
    }
    for (row = 0; row < n_rows; row++) {
        int ix = ix0 + row;
        for (si = 0; si < n_theta; si++) {
            if (!changed[row * n_theta + si]) {
                continue;
            }
            radii[ix * n_theta + si] = (float)work[row * n_theta + si];
            if (changed_mask != NULL) {
                changed_mask[ix * n_theta + si] = 1;
            }
        }
    }
    sc_mark_product(tile_mask, ntt, tile, changed, n_rows, ix0, n_theta, all_th, n_theta);
    free(ts);
    free(wx_all);
    free(changed);
    free(all_th);
    return 0;
}

/* Pick a carve strategy from how much A (and XYZ) moved. */
static int sc_carve_one(
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
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1,
    const ScProfile *profile,
    double *work,
    int *it,
    uint8_t *changed_mask,
    uint8_t *tile_mask,
    int ntt) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double dz = p1z - p0z;
    double da = a1 - a0;
    double xyz_len_sq = dx * dx + dy * dy + dz * dz;
    double step_a = d_theta;
    int n_a, n, i;
    if (fabs(da) >= 360.0 - 1e-6 && xyz_len_sq <= cell * cell) {
        /* Full revolution with almost no XYZ travel. */
        double tx, ty, tz;
        if (xyz_len_sq < 1e-18) {
            tx = p0x;
            ty = p0y;
            tz = p0z;
        } else {
            tx = p0x + 0.5 * dx;
            ty = p0y + 0.5 * dy;
            tz = p0z + 0.5 * dz;
        }
        return sc_carve_full_rev(
            radii, nx, n_theta, min_x, cell, d_theta, axis_y, axis_z, stock_radius, sin_t, cos_t, tile, tx, ty, tz,
            0.5 * (a0 + a1), profile, work, it, changed_mask, tile_mask, ntt);
    }
    if (fabs(da) <= step_a + 1e-9) {
        /* A stayed within one angle bin. */
        return sc_carve_constant(
            radii, nx, n_theta, min_x, cell, d_theta, axis_y, axis_z, stock_radius, sin_t, cos_t, tile, p0x, p0y, p0z,
            p1x, p1y, p1z, 0.5 * (a0 + a1), profile, work, it, changed_mask, tile_mask, ntt);
    }
    n_a = (int)ceil(fabs(da) / step_a) + 1;
    if (n_a > 4) {
        /* Large A change: sample poses instead of splitting into many tiny moves. */
        return sc_carve_moving(
            radii, nx, n_theta, min_x, cell, d_theta, axis_y, axis_z, stock_radius, sin_t, cos_t, tile, p0x, p0y, p0z,
            p1x, p1y, p1z, a0, a1, profile, work, it, changed_mask, tile_mask, ntt);
    }
    n = (int)ceil(fabs(da) / step_a);
    if (n < 1) {
        n = 1;
    }
    /* Modest A change: split into a few constant-A slices. */
    for (i = 0; i < n; i++) {
        double t0 = (double)i / (double)n;
        double t1 = (double)(i + 1) / (double)n;
        double ang = a0 + 0.5 * (t0 + t1) * da;
        int rc = sc_carve_constant(
            radii,
            nx,
            n_theta,
            min_x,
            cell,
            d_theta,
            axis_y,
            axis_z,
            stock_radius,
            sin_t,
            cos_t,
            tile,
            p0x + t0 * dx,
            p0y + t0 * dy,
            p0z + t0 * dz,
            p0x + t1 * dx,
            p0y + t1 * dy,
            p0z + t1 * dz,
            ang,
            profile,
            work,
            it,
            changed_mask,
            tile_mask,
            ntt);
        if (rc != 0) {
            return rc;
        }
    }
    return 0;
}

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
    int *laser_changed) {
    double *work;
    int *it;
    int i;
    uint8_t *local_mask = NULL;
    (void)ntx;
    if (radii == NULL || profile == NULL || nseg <= 0 || nx <= 0 || n_theta <= 0) {
        return 0;
    }
    if (profile->max_r <= 0.0 && profile->flute_z <= 0.0) {
        return 0;
    }
    work = (double *)malloc((size_t)nx * (size_t)n_theta * sizeof(double));
    it = (int *)malloc((size_t)n_theta * sizeof(int));
    if (work == NULL || it == NULL) {
        free(work);
        free(it);
        return -1;
    }
    /* Remember which occupancy cells dropped so the laser wipe stays on that footprint. */
    if (laser != NULL && laser->intensity != NULL && changed_mask == NULL) {
        local_mask = (uint8_t *)calloc((size_t)nx * (size_t)n_theta, 1);
        if (local_mask == NULL) {
            free(work);
            free(it);
            return -1;
        }
        changed_mask = local_mask;
    }
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        int rc = sc_carve_one(
            radii,
            nx,
            n_theta,
            min_x,
            cell,
            d_theta,
            axis_y,
            axis_z,
            stock_radius,
            sin_t,
            cos_t,
            tile,
            a[0],
            a[1],
            a[2],
            b[0],
            b[1],
            b[2],
            a0[i],
            a1[i],
            profile,
            work,
            it,
            changed_mask,
            tile_mask,
            ntt);
        if (rc != 0) {
            free(local_mask);
            free(work);
            free(it);
            return rc;
        }
    }
    if (laser != NULL && laser->intensity != NULL && changed_mask != NULL) {
        int ix;
        int ith;
        for (ix = 0; ix < nx; ix++) {
            for (ith = 0; ith < n_theta; ith++) {
                if (!changed_mask[(size_t)ix * (size_t)n_theta + (size_t)ith]) {
                    continue;
                }
                sc_laser_clear_coarse_cell(laser, ix, ith, min_x, 0.0, cell, d_theta, n_theta, laser_changed);
            }
        }
    }
    free(local_mask);
    free(work);
    free(it);
    return 0;
}
