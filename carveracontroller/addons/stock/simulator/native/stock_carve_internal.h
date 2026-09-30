/* Shared geometry: look up the tool shape, and test if a point is inside it. */
#ifndef CARVERA_STOCK_CARVE_INTERNAL_H
#define CARVERA_STOCK_CARVE_INTERNAL_H

#include "stock_carve.h"

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline double sc_clamp(double v, double lo, double hi) {
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

/* Remainder in [0, b), matching Python's `%`. */
static inline double sc_py_mod(double a, double b) {
    double m = fmod(a, b);
    if (m < 0.0) {
        m += b;
    }
    return m;
}

/* Spin Y/Z around X - that's the machine's A axis. */
static inline void sc_rotate_yz(double y, double z, double angle_deg, double *oy, double *oz) {
    double rad = angle_deg * (M_PI / 180.0);
    double c = cos(rad);
    double s = sin(rad);
    *oy = y * c - z * s;
    *oz = y * s + z * c;
}

double sc_sample_radius(const ScProfile *p, double z_rel);      /* radius at height above the tip */
double sc_sample_z_for_radius(const ScProfile *p, double dist); /* lowest height that has this radius */
double sc_max_radius_in_band(const ScProfile *p, double band_lo, double band_hi);

/* True if (x,y,z) sits inside the tool while the tip travels p0 -> p1. */
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
    const ScProfile *profile);

#endif
