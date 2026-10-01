/* Welded stock meshes in the Kivy vertex layout.
 *
 * Heightmap and cylindrical shells share corner vertices. Voxel chunks keep
 * unshared quads; a 16^3 chunk is small enough that the win is leaving Python.
 * Output stays under the uint16 index limit (65000 vertices per part).
 */
#include "stock_carve.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SC_MESH_MAX_VERTS 65000
#define HM_CLIFF 4.0f
#define HM_MERGE 1.0e-4f
#define HM_EXAG 3.0f
#define HM_MAX_SLOPE 1.73205080757f

typedef struct ScBuf {
    float *v;
    uint16_t *idx;
    int nv;
    int ni;
    int vcap;
    int icap;
} ScBuf;

void sc_mesh_batch_free(ScMeshBatch *batch) {
    int i;
    if (batch == NULL) {
        return;
    }
    for (i = 0; i < batch->nparts; i++) {
        free(batch->parts[i].verts);
        free(batch->parts[i].indices);
    }
    free(batch->parts);
    batch->parts = NULL;
    batch->nparts = 0;
    batch->cap = 0;
}

static void sc_buf_init(ScBuf *b) {
    memset(b, 0, sizeof(*b));
}

static void sc_buf_free(ScBuf *b) {
    free(b->v);
    free(b->idx);
    sc_buf_init(b);
}

static int sc_batch_add(ScMeshBatch *batch, ScBuf *b) {
    ScMeshPart *parts;
    int ncap;
    if (b->nv <= 0 || b->ni <= 0) {
        sc_buf_free(b);
        return 0;
    }
    if (batch->nparts >= batch->cap) {
        ncap = batch->cap > 0 ? batch->cap * 2 : 4;
        parts = (ScMeshPart *)realloc(batch->parts, (size_t)ncap * sizeof(ScMeshPart));
        if (parts == NULL) {
            return -1;
        }
        batch->parts = parts;
        batch->cap = ncap;
    }
    batch->parts[batch->nparts].verts = b->v;
    batch->parts[batch->nparts].indices = b->idx;
    batch->parts[batch->nparts].nverts = b->nv;
    batch->parts[batch->nparts].nindices = b->ni;
    batch->nparts++;
    sc_buf_init(b);
    return 0;
}

static int sc_buf_reserve(ScBuf *b, int add_v, int add_i) {
    int ncap;
    float *nv;
    uint16_t *ni;
    if (b->nv + add_v > b->vcap) {
        ncap = b->vcap > 0 ? b->vcap : 256;
        while (ncap < b->nv + add_v) {
            if (ncap > 8000000) {
                return -1;
            }
            ncap *= 2;
        }
        nv = (float *)realloc(b->v, (size_t)ncap * 12u * sizeof(float));
        if (nv == NULL) {
            return -1;
        }
        b->v = nv;
        b->vcap = ncap;
    }
    if (b->ni + add_i > b->icap) {
        ncap = b->icap > 0 ? b->icap : 512;
        while (ncap < b->ni + add_i) {
            if (ncap > 48000000) {
                return -1;
            }
            ncap *= 2;
        }
        ni = (uint16_t *)realloc(b->idx, (size_t)ncap * sizeof(uint16_t));
        if (ni == NULL) {
            return -1;
        }
        b->idx = ni;
        b->icap = ncap;
    }
    return 0;
}

static int sc_buf_vert(
    ScBuf *b,
    float x,
    float y,
    float z,
    float nx,
    float ny,
    float nz,
    float cr,
    float cg,
    float cb,
    float ca) {
    float *p;
    if (b->nv >= SC_MESH_MAX_VERTS) {
        return -2;
    }
    if (sc_buf_reserve(b, 1, 0) != 0) {
        return -1;
    }
    p = b->v + b->nv * 12;
    p[0] = x;
    p[1] = y;
    p[2] = z;
    p[3] = nx;
    p[4] = ny;
    p[5] = nz;
    p[6] = cr;
    p[7] = cg;
    p[8] = cb;
    p[9] = ca;
    p[10] = 0.f;
    p[11] = 0.f;
    return b->nv++;
}

static int sc_buf_tri(ScBuf *b, int a, int c, int d) {
    uint16_t *p;
    if (a < 0 || c < 0 || d < 0) {
        return -1;
    }
    if (sc_buf_reserve(b, 0, 3) != 0) {
        return -1;
    }
    p = b->idx + b->ni;
    p[0] = (uint16_t)a;
    p[1] = (uint16_t)c;
    p[2] = (uint16_t)d;
    b->ni += 3;
    return 0;
}

static int sc_buf_quad(ScBuf *b, int a, int c, int d, int e) {
    if (sc_buf_tri(b, a, c, d) != 0) {
        return -1;
    }
    return sc_buf_tri(b, a, d, e);
}

static int hm_valid(float h, float min_z) {
    return h > (float)(SC_OUTSIDE * 0.5) && h > min_z + HM_MERGE;
}

static float hm_at(const float *patch, int stride, int cx, int cy) {
    return patch[(cx + 1) * stride + (cy + 1)];
}

static void hm_slope_normal(float dzdx, float dzdy, float *nx, float *ny, float *nz) {
    float gx = HM_EXAG * dzdx;
    float gy = HM_EXAG * dzdy;
    float slope = sqrtf(gx * gx + gy * gy);
    float scale = 1.f;
    float x, y, z, len;
    if (slope > HM_MAX_SLOPE) {
        scale = HM_MAX_SLOPE / slope;
    }
    x = -gx * scale;
    y = -gy * scale;
    z = 1.f;
    len = sqrtf(x * x + y * y + z * z);
    if (len < 1e-12f) {
        *nx = 0.f;
        *ny = 0.f;
        *nz = 1.f;
        return;
    }
    *nx = x / len;
    *ny = y / len;
    *nz = z / len;
}

static void hm_cell_normal(
    const float *patch,
    int stride,
    int i,
    int j,
    float h,
    float min_z,
    float cliff,
    float cell,
    float *nx,
    float *ny,
    float *nz) {
    float hl = hm_at(patch, stride, i - 1, j);
    float hr = hm_at(patch, stride, i + 1, j);
    float hd = hm_at(patch, stride, i, j - 1);
    float hu = hm_at(patch, stride, i, j + 1);
    int ul = hm_valid(hl, min_z) && fabsf(hl - h) <= cliff;
    int ur = hm_valid(hr, min_z) && fabsf(hr - h) <= cliff;
    int ud = hm_valid(hd, min_z) && fabsf(hd - h) <= cliff;
    int uu = hm_valid(hu, min_z) && fabsf(hu - h) <= cliff;
    float dzdx = 0.f;
    float dzdy = 0.f;
    if (ul && ur) {
        dzdx = (hr - hl) / (2.f * cell);
    } else if (ur) {
        dzdx = (hr - h) / cell;
    } else if (ul) {
        dzdx = (h - hl) / cell;
    }
    if (ud && uu) {
        dzdy = (hu - hd) / (2.f * cell);
    } else if (uu) {
        dzdy = (hu - h) / cell;
    } else if (ud) {
        dzdy = (h - hd) / cell;
    }
    hm_slope_normal(dzdx, dzdy, nx, ny, nz);
}

static int hm_corner_vert(
    ScBuf *b,
    int *ids,
    int nrows,
    const float *cz,
    const uint8_t *share,
    int cstride,
    const float *patch,
    int stride,
    int i,
    int j,
    int cxi,
    int cyj,
    int j0,
    float origin_x,
    float origin_y,
    float cell,
    float min_z,
    float cliff,
    float cr,
    float cg,
    float cb,
    float ca) {
    int ci = i + cxi;
    int cj = j + cyj;
    int g = ci * cstride + cj;
    int slot = ci * nrows + (cj - j0);
    float z, nx, ny, nz, x, y;
    int id;
    if (share[g]) {
        /* Welded flat corner: every incident cell has the same height, so the
         * averaged height is exact and the shading normal stays +Z. */
        if (ids[slot] >= 0) {
            return ids[slot];
        }
        z = cz[g];
        nx = 0.f;
        ny = 0.f;
        nz = 1.f;
    } else {
        /* Steps keep crisp per-cell tops at the cell's own height. Averaging
         * neighbor heights here let adjacent cells disagree on a shared edge
         * while staying under the skirt threshold (open slits on walls). */
        float h = hm_at(patch, stride, i, j);
        z = h;
        hm_cell_normal(patch, stride, i, j, h, min_z, cliff, cell, &nx, &ny, &nz);
    }
    x = origin_x + (float)ci * cell;
    y = origin_y + (float)cj * cell;
    id = sc_buf_vert(b, x, y, z, nx, ny, nz, cr, cg, cb, ca);
    if (id >= 0 && share[g]) {
        ids[slot] = id;
    }
    return id;
}

static int hm_emit_axis_quad(
    ScBuf *b,
    float x0,
    float y0,
    float z0,
    float x1,
    float y1,
    float z1,
    float x2,
    float y2,
    float z2,
    float x3,
    float y3,
    float z3,
    float nx,
    float ny,
    float nz,
    float cr,
    float cg,
    float cb,
    float ca) {
    int i0, i1, i2, i3;
    if (b->nv + 4 > SC_MESH_MAX_VERTS) {
        return -2;
    }
    i0 = sc_buf_vert(b, x0, y0, z0, nx, ny, nz, cr, cg, cb, ca);
    i1 = sc_buf_vert(b, x1, y1, z1, nx, ny, nz, cr, cg, cb, ca);
    i2 = sc_buf_vert(b, x2, y2, z2, nx, ny, nz, cr, cg, cb, ca);
    i3 = sc_buf_vert(b, x3, y3, z3, nx, ny, nz, cr, cg, cb, ca);
    if (i0 < 0) {
        return i0;
    }
    if (i1 < 0) {
        return i1;
    }
    if (i2 < 0) {
        return i2;
    }
    if (i3 < 0) {
        return i3;
    }
    return sc_buf_quad(b, i0, i1, i2, i3);
}

static float hm_skirt_z(
    const float *patch,
    int stride,
    int ni,
    int nj,
    int at_grid,
    float min_z) {
    float nh;
    if (at_grid) {
        return min_z;
    }
    nh = hm_at(patch, stride, ni, nj);
    if (!hm_valid(nh, min_z)) {
        return min_z;
    }
    return nh;
}

static int hm_emit_skirts_cell(
    ScBuf *b,
    const float *patch,
    int stride,
    int i,
    int j,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    float origin_x,
    float origin_y,
    float cell,
    float min_z,
    float cr,
    float cg,
    float cb,
    float ca) {
    float h, x, y, zt0, zt1, zb0, zb1, nh;
    int rc;
    h = hm_at(patch, stride, i, j);
    /* Left (-X). */
    nh = hm_at(patch, stride, i - 1, j);
    if ((x0 + i == 0) || !hm_valid(nh, min_z) || (h - nh) > HM_MERGE) {
        zt0 = h;
        zt1 = h;
        zb0 = hm_skirt_z(patch, stride, i - 1, j, x0 + i == 0, min_z);
        zb1 = hm_skirt_z(patch, stride, i - 1, j, x0 + i == 0, min_z);
        if (0.5f * (zt0 + zt1) > 0.5f * (zb0 + zb1) + HM_MERGE) {
            x = origin_x + (float)i * cell;
            y = origin_y + (float)j * cell;
            rc = hm_emit_axis_quad(
                b, x, y, zt0, x, y + cell, zt1, x, y + cell, zb1, x, y, zb0, -1.f, 0.f, 0.f, cr, cg, cb, ca);
            if (rc != 0) {
                return rc;
            }
        }
    }
    /* Right (+X). */
    nh = hm_at(patch, stride, i + 1, j);
    if ((x0 + i + 1 >= grid_nx) || !hm_valid(nh, min_z) || (h - nh) > HM_MERGE) {
        zt0 = h;
        zt1 = h;
        zb0 = hm_skirt_z(patch, stride, i + 1, j, x0 + i + 1 >= grid_nx, min_z);
        zb1 = hm_skirt_z(patch, stride, i + 1, j, x0 + i + 1 >= grid_nx, min_z);
        if (0.5f * (zt0 + zt1) > 0.5f * (zb0 + zb1) + HM_MERGE) {
            x = origin_x + (float)(i + 1) * cell;
            y = origin_y + (float)j * cell;
            rc = hm_emit_axis_quad(
                b,
                x,
                y + cell,
                zt0,
                x,
                y,
                zt1,
                x,
                y,
                zb1,
                x,
                y + cell,
                zb0,
                1.f,
                0.f,
                0.f,
                cr,
                cg,
                cb,
                ca);
            if (rc != 0) {
                return rc;
            }
        }
    }
    /* Down (-Y). */
    nh = hm_at(patch, stride, i, j - 1);
    if ((y0 + j == 0) || !hm_valid(nh, min_z) || (h - nh) > HM_MERGE) {
        zt0 = h;
        zt1 = h;
        zb0 = hm_skirt_z(patch, stride, i, j - 1, y0 + j == 0, min_z);
        zb1 = hm_skirt_z(patch, stride, i, j - 1, y0 + j == 0, min_z);
        if (0.5f * (zt0 + zt1) > 0.5f * (zb0 + zb1) + HM_MERGE) {
            x = origin_x + (float)i * cell;
            y = origin_y + (float)j * cell;
            rc = hm_emit_axis_quad(
                b,
                x + cell,
                y,
                zt0,
                x,
                y,
                zt1,
                x,
                y,
                zb1,
                x + cell,
                y,
                zb0,
                0.f,
                -1.f,
                0.f,
                cr,
                cg,
                cb,
                ca);
            if (rc != 0) {
                return rc;
            }
        }
    }
    /* Up (+Y). */
    nh = hm_at(patch, stride, i, j + 1);
    if ((y0 + j + 1 >= grid_ny) || !hm_valid(nh, min_z) || (h - nh) > HM_MERGE) {
        zt0 = h;
        zt1 = h;
        zb0 = hm_skirt_z(patch, stride, i, j + 1, y0 + j + 1 >= grid_ny, min_z);
        zb1 = hm_skirt_z(patch, stride, i, j + 1, y0 + j + 1 >= grid_ny, min_z);
        if (0.5f * (zt0 + zt1) > 0.5f * (zb0 + zb1) + HM_MERGE) {
            x = origin_x + (float)i * cell;
            y = origin_y + (float)(j + 1) * cell;
            rc = hm_emit_axis_quad(
                b,
                x,
                y,
                zt0,
                x + cell,
                y,
                zt1,
                x + cell,
                y,
                zb1,
                x,
                y,
                zb0,
                0.f,
                1.f,
                0.f,
                cr,
                cg,
                cb,
                ca);
            if (rc != 0) {
                return rc;
            }
        }
    }
    return 0;
}

static int hm_emit_bottom(
    ScBuf *b,
    const uint8_t *valid,
    int gw,
    int gh,
    int j0,
    int j1,
    float origin_x,
    float origin_y,
    float min_z,
    float cell,
    float cr,
    float cg,
    float cb,
    float ca) {
    int rows = j1 - j0;
    int cols = gh;
    uint8_t *used;
    int i, j, rc;
    (void)cols;
    used = (uint8_t *)malloc((size_t)gw * (size_t)gh);
    if (used == NULL) {
        return -1;
    }
    memset(used, 0, (size_t)gw * (size_t)gh);
    for (i = 0; i < gw; i++) {
        for (j = 0; j < gh; j++) {
            if (!valid[i * gh + j]) {
                used[i * gh + j] = 1;
            }
        }
    }
    for (i = 0; i < gw; i++) {
        j = j0;
        while (j < j1) {
            int w, d, k, ok;
            float x0, y0, x1, y1;
            if (used[i * gh + j]) {
                j++;
                continue;
            }
            w = 1;
            while (j + w < j1 && !used[i * gh + (j + w)]) {
                w++;
            }
            d = 1;
            while (i + d < gw) {
                ok = 1;
                for (k = 0; k < w; k++) {
                    if (used[(i + d) * gh + (j + k)]) {
                        ok = 0;
                        break;
                    }
                }
                if (!ok) {
                    break;
                }
                d++;
            }
            for (k = 0; k < d; k++) {
                int t;
                for (t = 0; t < w; t++) {
                    used[(i + k) * gh + (j + t)] = 1;
                }
            }
            x0 = origin_x + (float)i * cell;
            y0 = origin_y + (float)j * cell;
            x1 = origin_x + (float)(i + d) * cell;
            y1 = origin_y + (float)(j + w) * cell;
            rc = hm_emit_axis_quad(
                b, x0, y0, min_z, x0, y1, min_z, x1, y1, min_z, x1, y0, min_z, 0.f, 0.f, -1.f, cr, cg, cb, ca);
            if (rc != 0) {
                free(used);
                return rc;
            }
            j += w;
        }
    }
    free(used);
    (void)rows;
    return 0;
}

static int hm_emit_rows(
    ScBuf *b,
    const float *patch,
    int stride,
    const uint8_t *valid,
    const float *cz,
    const uint8_t *share,
    int cstride,
    int gw,
    int gh,
    int j0,
    int j1,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    float origin_x,
    float origin_y,
    float cell,
    float min_z,
    float cliff,
    float cr,
    float cg,
    float cb,
    float ca) {
    int nrows = j1 - j0 + 1;
    int *ids;
    int i, j, nids;
    ids = NULL;
    nids = (gw + 1) * nrows;
    ids = (int *)malloc((size_t)nids * sizeof(int));
    if (ids == NULL) {
        return -1;
    }
    for (i = 0; i < nids; i++) {
        ids[i] = -1;
    }
    for (i = 0; i < gw; i++) {
        for (j = j0; j < j1; j++) {
            int i00, i10, i11, i01, rc;
            if (!valid[i * gh + j]) {
                continue;
            }
            i00 = hm_corner_vert(
                b, ids, nrows, cz, share, cstride, patch, stride, i, j, 0, 0, j0, origin_x, origin_y, cell,
                min_z, cliff, cr, cg, cb, ca);
            i10 = hm_corner_vert(
                b, ids, nrows, cz, share, cstride, patch, stride, i, j, 1, 0, j0, origin_x, origin_y, cell,
                min_z, cliff, cr, cg, cb, ca);
            i11 = hm_corner_vert(
                b, ids, nrows, cz, share, cstride, patch, stride, i, j, 1, 1, j0, origin_x, origin_y, cell,
                min_z, cliff, cr, cg, cb, ca);
            i01 = hm_corner_vert(
                b, ids, nrows, cz, share, cstride, patch, stride, i, j, 0, 1, j0, origin_x, origin_y, cell,
                min_z, cliff, cr, cg, cb, ca);
            if (i00 < 0 || i10 < 0 || i11 < 0 || i01 < 0) {
                free(ids);
                return i00 < 0 ? i00 : (i10 < 0 ? i10 : (i11 < 0 ? i11 : i01));
            }
            rc = sc_buf_quad(b, i00, i10, i11, i01);
            if (rc != 0) {
                free(ids);
                return rc;
            }
            rc = hm_emit_skirts_cell(
                b, patch, stride, i, j, x0, y0, grid_nx, grid_ny, origin_x, origin_y, cell, min_z, cr, cg, cb, ca);
            if (rc != 0) {
                free(ids);
                return rc;
            }
        }
    }
    free(ids);
    return hm_emit_bottom(b, valid, gw, gh, j0, j1, origin_x, origin_y, min_z, cell, cr, cg, cb, ca);
}

static int hm_emit_split(
    ScMeshBatch *out,
    const float *patch,
    int stride,
    const uint8_t *valid,
    const float *cz,
    const uint8_t *share,
    int cstride,
    int gw,
    int gh,
    int j0,
    int j1,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    float origin_x,
    float origin_y,
    float cell,
    float min_z,
    float cliff,
    float cr,
    float cg,
    float cb,
    float ca) {
    ScBuf buf;
    int rc, mid;
    sc_buf_init(&buf);
    rc = hm_emit_rows(
        &buf, patch, stride, valid, cz, share, cstride, gw, gh, j0, j1, x0, y0, grid_nx, grid_ny, origin_x, origin_y,
        cell, min_z, cliff, cr, cg, cb, ca);
    if (rc == 0) {
        return sc_batch_add(out, &buf);
    }
    sc_buf_free(&buf);
    if (rc != -2 || j1 - j0 <= 1) {
        return -1;
    }
    mid = j0 + (j1 - j0) / 2;
    if (hm_emit_split(
            out, patch, stride, valid, cz, share, cstride, gw, gh, j0, mid, x0, y0, grid_nx, grid_ny, origin_x,
            origin_y, cell, min_z, cliff, cr, cg, cb, ca) != 0) {
        return -1;
    }
    return hm_emit_split(
        out, patch, stride, valid, cz, share, cstride, gw, gh, mid, j1, x0, y0, grid_nx, grid_ny, origin_x, origin_y,
        cell, min_z, cliff, cr, cg, cb, ca);
}

static int hm_emit_uniform(
    ScMeshBatch *out,
    const float *patch,
    int stride,
    int gw,
    int gh,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    float origin_x,
    float origin_y,
    float min_z,
    float cell,
    float h,
    float cliff,
    float cr,
    float cg,
    float cb,
    float ca) {
    ScBuf buf;
    float x1 = origin_x + (float)gw * cell;
    float y1 = origin_y + (float)gh * cell;
    int side, rc;
    (void)cliff;
    sc_buf_init(&buf);
    rc = hm_emit_axis_quad(&buf, origin_x, origin_y, h, x1, origin_y, h, x1, y1, h, origin_x, y1, h, 0.f, 0.f, 1.f, cr, cg, cb, ca);
    if (rc != 0) {
        sc_buf_free(&buf);
        return -1;
    }
    if (h > min_z + HM_MERGE) {
        rc = hm_emit_axis_quad(
            &buf, origin_x, origin_y, min_z, origin_x, y1, min_z, x1, y1, min_z, x1, origin_y, min_z, 0.f, 0.f, -1.f, cr, cg, cb,
            ca);
        if (rc != 0) {
            sc_buf_free(&buf);
            return -1;
        }
    }
    for (side = 0; side < 4; side++) {
        int n = (side < 2) ? gh : gw;
        int j = 0;
        while (j < n) {
            int at_grid, need, w;
            float nh, zbot, x0e, y0e, x1e, y1e;
            if (side == 0) {
                at_grid = x0 == 0;
                nh = hm_at(patch, stride, -1, j);
            } else if (side == 1) {
                at_grid = x0 + gw >= grid_nx;
                nh = hm_at(patch, stride, gw, j);
            } else if (side == 2) {
                at_grid = y0 == 0;
                nh = hm_at(patch, stride, j, -1);
            } else {
                at_grid = y0 + gh >= grid_ny;
                nh = hm_at(patch, stride, j, gh);
            }
            need = at_grid || !hm_valid(nh, min_z) || (h - nh) > HM_MERGE;
            zbot = (at_grid || !hm_valid(nh, min_z)) ? min_z : nh;
            if (!need || h <= zbot + HM_MERGE) {
                j++;
                continue;
            }
            w = 1;
            while (j + w < n) {
                int ag;
                float nh2, zb2;
                if (side == 0) {
                    ag = x0 == 0;
                    nh2 = hm_at(patch, stride, -1, j + w);
                } else if (side == 1) {
                    ag = x0 + gw >= grid_nx;
                    nh2 = hm_at(patch, stride, gw, j + w);
                } else if (side == 2) {
                    ag = y0 == 0;
                    nh2 = hm_at(patch, stride, j + w, -1);
                } else {
                    ag = y0 + gh >= grid_ny;
                    nh2 = hm_at(patch, stride, j + w, gh);
                }
                if (!(ag || !hm_valid(nh2, min_z) || (h - nh2) > HM_MERGE)) {
                    break;
                }
                zb2 = (ag || !hm_valid(nh2, min_z)) ? min_z : nh2;
                if (fabsf(zb2 - zbot) > HM_MERGE) {
                    break;
                }
                w++;
            }
            if (side == 0) {
                x0e = origin_x;
                y0e = origin_y + (float)j * cell;
                y1e = origin_y + (float)(j + w) * cell;
                rc = hm_emit_axis_quad(&buf, x0e, y0e, h, x0e, y1e, h, x0e, y1e, zbot, x0e, y0e, zbot, -1.f, 0.f, 0.f, cr, cg, cb, ca);
            } else if (side == 1) {
                x0e = x1;
                y0e = origin_y + (float)j * cell;
                y1e = origin_y + (float)(j + w) * cell;
                rc = hm_emit_axis_quad(&buf, x0e, y1e, h, x0e, y0e, h, x0e, y0e, zbot, x0e, y1e, zbot, 1.f, 0.f, 0.f, cr, cg, cb, ca);
            } else if (side == 2) {
                x0e = origin_x + (float)j * cell;
                x1e = origin_x + (float)(j + w) * cell;
                y0e = origin_y;
                rc = hm_emit_axis_quad(&buf, x1e, y0e, h, x0e, y0e, h, x0e, y0e, zbot, x1e, y0e, zbot, 0.f, -1.f, 0.f, cr, cg, cb, ca);
            } else {
                x0e = origin_x + (float)j * cell;
                x1e = origin_x + (float)(j + w) * cell;
                y0e = y1;
                rc = hm_emit_axis_quad(&buf, x0e, y0e, h, x1e, y0e, h, x1e, y0e, zbot, x0e, y0e, zbot, 0.f, 1.f, 0.f, cr, cg, cb, ca);
            }
            if (rc != 0) {
                sc_buf_free(&buf);
                return -1;
            }
            j += w;
        }
    }
    return sc_batch_add(out, &buf);
}

int sc_mesh_heightmap(
    const float *patch,
    int gw,
    int gh,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    double origin_x,
    double origin_y,
    double min_z,
    double cell,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out) {
    int stride, i, j, ncorner, any;
    float fmin, fcell, fox, foy, cliff, h0, hmin, hmax;
    float fcr, fcg, fcb, fca;
    uint8_t *valid;
    uint8_t *share;
    float *cz;
    int all_valid, uniform;
    if (out == NULL || patch == NULL || gw <= 0 || gh <= 0 || cell <= 0.0) {
        return -1;
    }
    stride = gh + 2;
    fmin = (float)min_z;
    fcell = (float)cell;
    fox = (float)origin_x;
    foy = (float)origin_y;
    cliff = HM_CLIFF * fcell;
    fcr = (float)cr;
    fcg = (float)cg;
    fcb = (float)cb;
    fca = (float)ca;
    valid = (uint8_t *)malloc((size_t)gw * (size_t)gh);
    ncorner = (gw + 1) * (gh + 1);
    share = (uint8_t *)malloc((size_t)ncorner);
    cz = (float *)malloc((size_t)ncorner * sizeof(float));
    if (valid == NULL || share == NULL || cz == NULL) {
        free(valid);
        free(share);
        free(cz);
        return -1;
    }
    any = 0;
    all_valid = 1;
    hmin = 1e30f;
    hmax = -1e30f;
    h0 = 0.f;
    for (i = 0; i < gw; i++) {
        for (j = 0; j < gh; j++) {
            float h = hm_at(patch, stride, i, j);
            int ok = hm_valid(h, fmin);
            valid[i * gh + j] = (uint8_t)ok;
            if (!ok) {
                all_valid = 0;
                continue;
            }
            any = 1;
            if (h < hmin) {
                hmin = h;
            }
            if (h > hmax) {
                hmax = h;
            }
            h0 = h;
        }
    }
    if (!any) {
        free(valid);
        free(share);
        free(cz);
        return 0;
    }
    uniform = all_valid && (hmax - hmin) <= HM_MERGE;
    if (uniform) {
        int rc = hm_emit_uniform(
            out, patch, stride, gw, gh, x0, y0, grid_nx, grid_ny, fox, foy, fmin, fcell, h0, cliff, fcr, fcg, fcb, fca);
        free(valid);
        free(share);
        free(cz);
        return rc;
    }
    for (i = 0; i <= gw; i++) {
        for (j = 0; j <= gh; j++) {
            float sum = 0.f;
            float mn = 1e30f;
            float mx = -1e30f;
            int n = 0;
            int ax, ay;
            int slot = i * (gh + 1) + j;
            for (ax = i - 1; ax <= i; ax++) {
                for (ay = j - 1; ay <= j; ay++) {
                    float h = hm_at(patch, stride, ax, ay);
                    if (!hm_valid(h, fmin)) {
                        continue;
                    }
                    if (h < mn) {
                        mn = h;
                    }
                    if (h > mx) {
                        mx = h;
                    }
                    sum += h;
                    n++;
                }
            }
            if (n > 0 && (mx - mn) <= HM_MERGE) {
                /* Welded flat corner. Steps stay per-cell at their own height:
                 * averaging neighbor heights here let adjacent cells disagree
                 * on a shared edge while staying under the skirt threshold,
                 * leaving open slits on walls (see hm_corner_vert). */
                share[slot] = 1;
                cz[slot] = sum / (float)n;
            } else {
                share[slot] = 0;
                cz[slot] = 0.f;
            }
        }
    }
    {
        /* Split up front. Retrying a strip that cannot fit wastes the vertices
         * it builds before hitting the uint16 cap. */
        int rows_fit = SC_MESH_MAX_VERTS / (gw + 1);
        int j, rc;
        if (rows_fit > 4) {
            rows_fit = (rows_fit * 2) / 3;
        }
        if (rows_fit < 1) {
            rows_fit = 1;
        }
        for (j = 0; j < gh; j += rows_fit) {
            int j1 = j + rows_fit;
            if (j1 > gh) {
                j1 = gh;
            }
            rc = hm_emit_split(
                out, patch, stride, valid, cz, share, gh + 1, gw, gh, j, j1, x0, y0, grid_nx, grid_ny, fox, foy, fcell,
                fmin, cliff, fcr, fcg, fcb, fca);
            if (rc != 0) {
                free(valid);
                free(share);
                free(cz);
                return -1;
            }
        }
        free(valid);
        free(share);
        free(cz);
        return 0;
    }
}

static void cyl_cross(const float *a, const float *b, const float *c, double *n) {
    double bx = (double)b[0] - (double)a[0];
    double by = (double)b[1] - (double)a[1];
    double bz = (double)b[2] - (double)a[2];
    double cx = (double)c[0] - (double)a[0];
    double cy = (double)c[1] - (double)a[1];
    double cz = (double)c[2] - (double)a[2];
    n[0] = by * cz - bz * cy;
    n[1] = bz * cx - bx * cz;
    n[2] = bx * cy - by * cx;
}

static int cyl_use_b(const float *verts, int i00, int i10, int i11, int i01, double ay, double az) {
    const float *p00 = verts + i00 * 12;
    const float *p10 = verts + i10 * 12;
    const float *p11 = verts + i11 * 12;
    const float *p01 = verts + i01 * 12;
    double hy = 0.25 * ((double)p00[1] + (double)p10[1] + (double)p11[1] + (double)p01[1]) - ay;
    double hz = 0.25 * ((double)p00[2] + (double)p10[2] + (double)p11[2] + (double)p01[2]) - az;
    double n1[3], n2[3];
    double s1, s2, score_a, score_b;
    cyl_cross(p00, p10, p11, n1);
    cyl_cross(p00, p11, p01, n2);
    s1 = n1[1] * hy + n1[2] * hz;
    s2 = n2[1] * hy + n2[2] * hz;
    score_a = s1 < s2 ? s1 : s2;
    cyl_cross(p10, p11, p01, n1);
    cyl_cross(p10, p01, p00, n2);
    s1 = n1[1] * hy + n1[2] * hz;
    s2 = n2[1] * hy + n2[2] * hz;
    score_b = s1 < s2 ? s1 : s2;
    return score_b > score_a;
}

static int cyl_draw_r(float rr, double floor_r, double *r) {
    if (rr < 0.f) {
        return 0;
    }
    *r = (double)rr < floor_r ? floor_r : (double)rr;
    return 1;
}

static int cyl_emit_cap(
    ScBuf *b,
    const float *radii,
    int n_theta,
    int local_ix,
    int global_ix,
    double min_x,
    double cell,
    double ay,
    double az,
    const double *sin_t,
    const double *cos_t,
    double floor_r,
    float sign,
    float cr,
    float cg,
    float cb,
    float ca) {
    int *ring;
    int it, center, any;
    float x;
    ring = (int *)malloc((size_t)n_theta * sizeof(int));
    if (ring == NULL) {
        return -1;
    }
    any = 0;
    x = (float)(min_x + ((double)global_ix + 0.5) * cell);
    for (it = 0; it < n_theta; it++) {
        double r;
        int id;
        if (!cyl_draw_r(radii[local_ix * n_theta + it], floor_r, &r)) {
            ring[it] = -1;
            continue;
        }
        id = sc_buf_vert(
            b, x, (float)(ay + r * sin_t[it]), (float)(az + r * cos_t[it]), sign, 0.f, 0.f, cr, cg, cb, ca);
        if (id < 0) {
            free(ring);
            return id;
        }
        ring[it] = id;
        any = 1;
    }
    if (!any) {
        free(ring);
        return 0;
    }
    center = sc_buf_vert(b, x, (float)ay, (float)az, sign, 0.f, 0.f, cr, cg, cb, ca);
    if (center < 0) {
        free(ring);
        return center;
    }
    for (it = 0; it < n_theta; it++) {
        int a = ring[it];
        int c = ring[(it + 1) % n_theta];
        int rc;
        if (a < 0 || c < 0) {
            continue;
        }
        if (sign < 0.f) {
            rc = sc_buf_tri(b, center, a, c);
        } else {
            rc = sc_buf_tri(b, center, c, a);
        }
        if (rc != 0) {
            free(ring);
            return rc;
        }
    }
    free(ring);
    return 0;
}

/* Radius-field normal. A purely radial normal lights a relief as a smooth bar. */
static void cyl_neighbor_r(
    const float *radii, int nx, int n_theta, int ix, int it, double floor_r, double fallback, double *r) {
    int itw;
    if (ix < 0 || ix >= nx) {
        *r = fallback;
        return;
    }
    itw = it % n_theta;
    if (itw < 0) {
        itw += n_theta;
    }
    if (!cyl_draw_r(radii[(size_t)ix * (size_t)n_theta + (size_t)itw], floor_r, r)) {
        *r = fallback;
    }
}

static void cyl_shell_normal(
    const float *radii,
    int nx,
    int n_theta,
    int local_ix,
    int global_ix,
    int it,
    double min_x,
    double cell,
    double ay,
    double az,
    const double *sin_t,
    const double *cos_t,
    double floor_r,
    float *out_x,
    float *out_y,
    float *out_z) {
    double rc, rxm, rxp, rtm, rtp;
    double pxm[3], pxp[3], ptm[3], ptp[3];
    double tx0, tx1, tx2, tt0, tt1, tt2;
    double n0, n1, n2, len, outward;
    int lxm, lxp, itm, itp;
    int gxm, gxp;

    cyl_neighbor_r(radii, nx, n_theta, local_ix, it, floor_r, floor_r, &rc);
    lxm = local_ix > 0 ? local_ix - 1 : local_ix;
    lxp = local_ix + 1 < nx ? local_ix + 1 : local_ix;
    gxm = global_ix + (lxm - local_ix);
    gxp = global_ix + (lxp - local_ix);
    itm = it > 0 ? it - 1 : n_theta - 1;
    itp = it + 1 < n_theta ? it + 1 : 0;
    cyl_neighbor_r(radii, nx, n_theta, lxm, it, floor_r, rc, &rxm);
    cyl_neighbor_r(radii, nx, n_theta, lxp, it, floor_r, rc, &rxp);
    cyl_neighbor_r(radii, nx, n_theta, local_ix, itm, floor_r, rc, &rtm);
    cyl_neighbor_r(radii, nx, n_theta, local_ix, itp, floor_r, rc, &rtp);

    pxm[0] = min_x + ((double)gxm + 0.5) * cell;
    pxm[1] = ay + rxm * sin_t[it];
    pxm[2] = az + rxm * cos_t[it];
    pxp[0] = min_x + ((double)gxp + 0.5) * cell;
    pxp[1] = ay + rxp * sin_t[it];
    pxp[2] = az + rxp * cos_t[it];
    ptm[0] = min_x + ((double)global_ix + 0.5) * cell;
    ptm[1] = ay + rtm * sin_t[itm];
    ptm[2] = az + rtm * cos_t[itm];
    ptp[0] = ptm[0];
    ptp[1] = ay + rtp * sin_t[itp];
    ptp[2] = az + rtp * cos_t[itp];
    tx0 = pxp[0] - pxm[0];
    tx1 = pxp[1] - pxm[1];
    tx2 = pxp[2] - pxm[2];
    tt0 = ptp[0] - ptm[0];
    tt1 = ptp[1] - ptm[1];
    tt2 = ptp[2] - ptm[2];
    /* cross(dP/dx, dP/dθ) points outward on a constant-radius tube. */
    n0 = tx1 * tt2 - tx2 * tt1;
    n1 = tx2 * tt0 - tx0 * tt2;
    n2 = tx0 * tt1 - tx1 * tt0;
    outward = n1 * sin_t[it] + n2 * cos_t[it];
    if (outward < 0.0) {
        n0 = -n0;
        n1 = -n1;
        n2 = -n2;
    }
    len = sqrt(n0 * n0 + n1 * n1 + n2 * n2);
    if (len < 1e-12) {
        *out_x = 0.f;
        *out_y = (float)sin_t[it];
        *out_z = (float)cos_t[it];
        return;
    }
    *out_x = (float)(n0 / len);
    *out_y = (float)(n1 / len);
    *out_z = (float)(n2 / len);
}

int sc_mesh_cylinder(
    const float *radii,
    int nx,
    int n_theta,
    int ix0,
    int nx_total,
    double min_x,
    double cell,
    double axis_y,
    double axis_z,
    const double *sin_t,
    const double *cos_t,
    double floor_r,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out) {
    float fcr, fcg, fcb, fca;
    int ix;
    if (out == NULL || radii == NULL || sin_t == NULL || cos_t == NULL || nx <= 0 || n_theta < 3 || cell <= 0.0) {
        return -1;
    }
    fcr = (float)cr;
    fcg = (float)cg;
    fcb = (float)cb;
    fca = (float)ca;
    if (nx < 2) {
        ScBuf buf;
        int rc = 0;
        sc_buf_init(&buf);
        if (ix0 == 0) {
            rc = cyl_emit_cap(&buf, radii, n_theta, 0, ix0, min_x, cell, axis_y, axis_z, sin_t, cos_t, floor_r, -1.f, fcr, fcg, fcb, fca);
        }
        if (rc == 0 && ix0 + nx >= nx_total) {
            rc = cyl_emit_cap(
                &buf, radii, n_theta, nx - 1, ix0 + nx - 1, min_x, cell, axis_y, axis_z, sin_t, cos_t, floor_r, 1.f, fcr, fcg, fcb,
                fca);
        }
        if (rc != 0) {
            sc_buf_free(&buf);
            return -1;
        }
        return sc_batch_add(out, &buf);
    }
    ix = 0;
    while (ix < nx) {
        ScBuf buf;
        int *ids;
        int remain = nx - ix;
        int cap_lo = (ix == 0 && ix0 == 0);
        int room, include_hi, local, it, rc;
        int cap_budget = cap_lo ? (n_theta + 1) : 0;
        int room_with_hi = (SC_MESH_MAX_VERTS - cap_budget - (n_theta + 1)) / n_theta;
        if (room_with_hi < 2) {
            room_with_hi = 2;
        }
        if (ix0 + nx >= nx_total && remain <= room_with_hi) {
            room = remain;
            include_hi = 1;
        } else {
            room = (SC_MESH_MAX_VERTS - cap_budget) / n_theta;
            if (room < 2) {
                room = 2;
            }
            if (room > remain) {
                room = remain;
            }
            include_hi = 0;
        }
        sc_buf_init(&buf);
        ids = (int *)malloc((size_t)room * (size_t)n_theta * sizeof(int));
        if (ids == NULL) {
            return -1;
        }
        for (local = 0; local < room; local++) {
            int gix = ix0 + ix + local;
            float x = (float)(min_x + ((double)gix + 0.5) * cell);
            for (it = 0; it < n_theta; it++) {
                double r;
                int id = -1;
                float snx, sny, snz;
                float rr = radii[(ix + local) * n_theta + it];
                if (cyl_draw_r(rr, floor_r, &r)) {
                    cyl_shell_normal(
                        radii, nx, n_theta, ix + local, gix, it, min_x, cell, axis_y, axis_z, sin_t, cos_t, floor_r, &snx,
                        &sny, &snz);
                    id = sc_buf_vert(
                        &buf,
                        x,
                        (float)(axis_y + r * sin_t[it]),
                        (float)(axis_z + r * cos_t[it]),
                        snx,
                        sny,
                        snz,
                        fcr,
                        fcg,
                        fcb,
                        fca);
                    if (id < 0) {
                        free(ids);
                        sc_buf_free(&buf);
                        return -1;
                    }
                }
                ids[local * n_theta + it] = id;
            }
        }
        for (local = 0; local < room - 1; local++) {
            for (it = 0; it < n_theta; it++) {
                int it1 = (it + 1) % n_theta;
                int i00 = ids[local * n_theta + it];
                int i10 = ids[(local + 1) * n_theta + it];
                int i11 = ids[(local + 1) * n_theta + it1];
                int i01 = ids[local * n_theta + it1];
                if (i00 < 0 || i10 < 0 || i11 < 0 || i01 < 0) {
                    continue;
                }
                if (cyl_use_b(buf.v, i00, i10, i11, i01, axis_y, axis_z)) {
                    rc = sc_buf_quad(&buf, i10, i11, i01, i00);
                } else {
                    rc = sc_buf_quad(&buf, i00, i10, i11, i01);
                }
                if (rc != 0) {
                    free(ids);
                    sc_buf_free(&buf);
                    return -1;
                }
            }
        }
        free(ids);
        if (cap_lo) {
            rc = cyl_emit_cap(&buf, radii, n_theta, ix, ix0 + ix, min_x, cell, axis_y, axis_z, sin_t, cos_t, floor_r, -1.f, fcr, fcg, fcb, fca);
            if (rc != 0) {
                sc_buf_free(&buf);
                return -1;
            }
        }
        if (include_hi) {
            rc = cyl_emit_cap(
                &buf, radii, n_theta, ix + room - 1, ix0 + ix + room - 1, min_x, cell, axis_y, axis_z, sin_t, cos_t, floor_r,
                1.f, fcr, fcg, fcb, fca);
            if (rc != 0) {
                sc_buf_free(&buf);
                return -1;
            }
        }
        if (sc_batch_add(out, &buf) != 0) {
            sc_buf_free(&buf);
            return -1;
        }
        if (ix + room >= nx) {
            break;
        }
        ix += room - 1;
    }
    return 0;
}

static int voxel_solid(const uint8_t *occ, const uint8_t *valid, int cs, int i, int j, int k) {
    int id;
    if (i < 0 || j < 0 || k < 0 || i >= cs || j >= cs || k >= cs) {
        return 0;
    }
    id = (i * cs + j) * cs + k;
    if (valid != NULL && !valid[id]) {
        return 0;
    }
    if (occ == NULL) {
        return 1;
    }
    return occ[id] != 0;
}

static int voxel_face_bit(int mode, const uint8_t *face, int cs, int a, int b) {
    if (mode == 1) {
        return 1;
    }
    if (mode == 2 && face != NULL) {
        return face[a * cs + b] != 0;
    }
    return 0;
}

static int voxel_flush_room(ScMeshBatch *batch, ScBuf *b, int need) {
    if (b->nv + need <= SC_MESH_MAX_VERTS) {
        return 0;
    }
    if (b->nv <= 0) {
        return -1;
    }
    if (sc_batch_add(batch, b) != 0) {
        return -1;
    }
    sc_buf_init(b);
    return 0;
}

static int voxel_emit_corners(
    ScMeshBatch *batch,
    ScBuf *b,
    float c0[3],
    float c1[3],
    float c2[3],
    float c3[3],
    float nx,
    float ny,
    float nz,
    float cr,
    float cg,
    float cb,
    float ca) {
    int i0, i1, i2, i3, rc;
    rc = voxel_flush_room(batch, b, 4);
    if (rc != 0) {
        return rc;
    }
    i0 = sc_buf_vert(b, c0[0], c0[1], c0[2], nx, ny, nz, cr, cg, cb, ca);
    i1 = sc_buf_vert(b, c1[0], c1[1], c1[2], nx, ny, nz, cr, cg, cb, ca);
    i2 = sc_buf_vert(b, c2[0], c2[1], c2[2], nx, ny, nz, cr, cg, cb, ca);
    i3 = sc_buf_vert(b, c3[0], c3[1], c3[2], nx, ny, nz, cr, cg, cb, ca);
    if (i0 < 0 || i1 < 0 || i2 < 0 || i3 < 0) {
        return -1;
    }
    return sc_buf_quad(b, i0, i1, i2, i3);
}

static int voxel_emit_rect(
    ScMeshBatch *batch,
    ScBuf *b,
    int axis,
    int sign,
    int index,
    int i0,
    int j0,
    int i1,
    int j1,
    float ox,
    float oy,
    float oz,
    float vs,
    float cr,
    float cg,
    float cb,
    float ca) {
    float plane = (axis == 0 ? ox : (axis == 1 ? oy : oz)) + (float)(index + (sign > 0 ? 1 : 0)) * vs;
    float a0, a1, b0, b1;
    float c0[3], c1[3], c2[3], c3[3];
    float n[3] = {0.f, 0.f, 0.f};
    n[axis] = (float)sign;
    if (axis == 0) {
        a0 = oy + (float)i0 * vs;
        a1 = oy + (float)i1 * vs;
        b0 = oz + (float)j0 * vs;
        b1 = oz + (float)j1 * vs;
        if (sign > 0) {
            c0[0] = plane;
            c0[1] = a0;
            c0[2] = b0;
            c1[0] = plane;
            c1[1] = a1;
            c1[2] = b0;
            c2[0] = plane;
            c2[1] = a1;
            c2[2] = b1;
            c3[0] = plane;
            c3[1] = a0;
            c3[2] = b1;
        } else {
            c0[0] = plane;
            c0[1] = a0;
            c0[2] = b0;
            c1[0] = plane;
            c1[1] = a0;
            c1[2] = b1;
            c2[0] = plane;
            c2[1] = a1;
            c2[2] = b1;
            c3[0] = plane;
            c3[1] = a1;
            c3[2] = b0;
        }
    } else if (axis == 1) {
        a0 = ox + (float)i0 * vs;
        a1 = ox + (float)i1 * vs;
        b0 = oz + (float)j0 * vs;
        b1 = oz + (float)j1 * vs;
        if (sign > 0) {
            c0[0] = a0;
            c0[1] = plane;
            c0[2] = b0;
            c1[0] = a0;
            c1[1] = plane;
            c1[2] = b1;
            c2[0] = a1;
            c2[1] = plane;
            c2[2] = b1;
            c3[0] = a1;
            c3[1] = plane;
            c3[2] = b0;
        } else {
            c0[0] = a0;
            c0[1] = plane;
            c0[2] = b0;
            c1[0] = a1;
            c1[1] = plane;
            c1[2] = b0;
            c2[0] = a1;
            c2[1] = plane;
            c2[2] = b1;
            c3[0] = a0;
            c3[1] = plane;
            c3[2] = b1;
        }
    } else {
        a0 = ox + (float)i0 * vs;
        a1 = ox + (float)i1 * vs;
        b0 = oy + (float)j0 * vs;
        b1 = oy + (float)j1 * vs;
        if (sign > 0) {
            c0[0] = a0;
            c0[1] = b0;
            c0[2] = plane;
            c1[0] = a1;
            c1[1] = b0;
            c1[2] = plane;
            c2[0] = a1;
            c2[1] = b1;
            c2[2] = plane;
            c3[0] = a0;
            c3[1] = b1;
            c3[2] = plane;
        } else {
            c0[0] = a0;
            c0[1] = b0;
            c0[2] = plane;
            c1[0] = a0;
            c1[1] = b1;
            c1[2] = plane;
            c2[0] = a1;
            c2[1] = b1;
            c2[2] = plane;
            c3[0] = a1;
            c3[1] = b0;
            c3[2] = plane;
        }
    }
    return voxel_emit_corners(batch, b, c0, c1, c2, c3, n[0], n[1], n[2], cr, cg, cb, ca);
}

static int voxel_greedy_mask(
    ScMeshBatch *batch,
    ScBuf *b,
    uint8_t *mask,
    int rows,
    int cols,
    int axis,
    int sign,
    int index,
    float ox,
    float oy,
    float oz,
    float vs,
    float cr,
    float cg,
    float cb,
    float ca) {
    uint8_t *used;
    int i, j, any, all;
    any = 0;
    all = 1;
    for (i = 0; i < rows * cols; i++) {
        if (mask[i]) {
            any = 1;
        } else {
            all = 0;
        }
    }
    if (!any) {
        return 0;
    }
    if (all) {
        return voxel_emit_rect(batch, b, axis, sign, index, 0, 0, rows, cols, ox, oy, oz, vs, cr, cg, cb, ca);
    }
    used = (uint8_t *)malloc((size_t)rows * (size_t)cols);
    if (used == NULL) {
        return -1;
    }
    for (i = 0; i < rows * cols; i++) {
        used[i] = mask[i] ? 0 : 1;
    }
    for (i = 0; i < rows; i++) {
        j = 0;
        while (j < cols) {
            int w, d, k, rc;
            if (used[i * cols + j]) {
                j++;
                continue;
            }
            w = 1;
            while (j + w < cols && !used[i * cols + (j + w)]) {
                w++;
            }
            d = 1;
            while (i + d < rows) {
                int ok = 1;
                for (k = 0; k < w; k++) {
                    if (used[(i + d) * cols + (j + k)]) {
                        ok = 0;
                        break;
                    }
                }
                if (!ok) {
                    break;
                }
                d++;
            }
            for (k = 0; k < d; k++) {
                int t;
                for (t = 0; t < w; t++) {
                    used[(i + k) * cols + (j + t)] = 1;
                }
            }
            rc = voxel_emit_rect(batch, b, axis, sign, index, i, j, i + d, j + w, ox, oy, oz, vs, cr, cg, cb, ca);
            if (rc != 0) {
                free(used);
                return rc;
            }
            j += w;
        }
    }
    free(used);
    return 0;
}

static int voxel_neighbor(
    const uint8_t *occ,
    const uint8_t *valid,
    int cs,
    int axis,
    int plus,
    int i,
    int j,
    int k,
    int face_mode,
    const uint8_t *face) {
    int ni = i, nj = j, nk = k;
    if (axis == 0) {
        ni = i + (plus ? 1 : -1);
    } else if (axis == 1) {
        nj = j + (plus ? 1 : -1);
    } else {
        nk = k + (plus ? 1 : -1);
    }
    if (ni >= 0 && nj >= 0 && nk >= 0 && ni < cs && nj < cs && nk < cs) {
        return voxel_solid(occ, valid, cs, ni, nj, nk);
    }
    if (axis == 0) {
        return voxel_face_bit(face_mode, face, cs, j, k);
    }
    if (axis == 1) {
        return voxel_face_bit(face_mode, face, cs, i, k);
    }
    return voxel_face_bit(face_mode, face, cs, i, j);
}

int sc_mesh_voxel_chunk(
    const uint8_t *occ,
    const uint8_t *valid,
    int cs,
    const int face_mode[6],
    const uint8_t *const faces[6],
    double ox,
    double oy,
    double oz,
    double voxel,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out) {
    ScBuf buf;
    uint8_t *mask;
    float fox, foy, foz, fvs, fcr, fcg, fcb, fca;
    int axis;
    if (out == NULL || cs <= 0 || voxel <= 0.0 || face_mode == NULL) {
        return -1;
    }
    fox = (float)ox;
    foy = (float)oy;
    foz = (float)oz;
    fvs = (float)voxel;
    fcr = (float)cr;
    fcg = (float)cg;
    fcb = (float)cb;
    fca = (float)ca;
    mask = (uint8_t *)malloc((size_t)cs * (size_t)cs);
    if (mask == NULL) {
        return -1;
    }
    sc_buf_init(&buf);
    for (axis = 0; axis < 3; axis++) {
        int plus;
        for (plus = 1; plus >= 0; plus--) {
            int face_i = axis * 2 + (plus ? 0 : 1);
            int mode = face_mode[face_i];
            const uint8_t *face = faces != NULL ? faces[face_i] : NULL;
            int i0 = 0;
            int i1 = cs;
            int index;
            /* A solid block only exposes the outer slice on this side. */
            if (occ == NULL && valid == NULL) {
                if (mode == 1) {
                    continue;
                }
                i0 = plus ? cs - 1 : 0;
                i1 = i0 + 1;
            }
            for (index = i0; index < i1; index++) {
                int a, b, any, rc;
                any = 0;
                for (a = 0; a < cs; a++) {
                    for (b = 0; b < cs; b++) {
                        int solid, covered;
                        if (axis == 0) {
                            solid = voxel_solid(occ, valid, cs, index, a, b);
                            covered = voxel_neighbor(occ, valid, cs, 0, plus, index, a, b, mode, face);
                        } else if (axis == 1) {
                            solid = voxel_solid(occ, valid, cs, a, index, b);
                            covered = voxel_neighbor(occ, valid, cs, 1, plus, a, index, b, mode, face);
                        } else {
                            solid = voxel_solid(occ, valid, cs, a, b, index);
                            covered = voxel_neighbor(occ, valid, cs, 2, plus, a, b, index, mode, face);
                        }
                        mask[a * cs + b] = (uint8_t)(solid && !covered);
                        if (mask[a * cs + b]) {
                            any = 1;
                        }
                    }
                }
                if (!any) {
                    continue;
                }
                rc = voxel_greedy_mask(
                    out, &buf, mask, cs, cs, axis, plus ? 1 : -1, index, fox, foy, foz, fvs, fcr, fcg, fcb, fca);
                if (rc != 0) {
                    free(mask);
                    sc_buf_free(&buf);
                    return -1;
                }
            }
        }
    }
    free(mask);
    if (sc_batch_add(out, &buf) != 0) {
        sc_buf_free(&buf);
        return -1;
    }
    return 0;
}
