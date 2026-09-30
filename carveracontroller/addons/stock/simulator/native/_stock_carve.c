/* Python entry points. Unpack NumPy buffers, run the C kernels, return dirty tiles.
 * Heightmap and cylindrical drop the GIL while carving; voxel cannot, because it
 * calls back into Python for each chunk.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "stock_carve.h"

#include <string.h>

/* Require a C-contiguous buffer so the kernels can index it as a flat array. */
static int sc_get_buffer(PyObject *obj, Py_buffer *view, int writable) {
    int flags = writable ? PyBUF_WRITABLE | PyBUF_ND : PyBUF_ND;
    if (PyObject_GetBuffer(obj, view, flags) != 0) {
        return -1;
    }
    if (!PyBuffer_IsContiguous(view, 'C')) {
        PyErr_SetString(PyExc_ValueError, "stock carve buffer must be C-contiguous");
        PyBuffer_Release(view);
        return -1;
    }
    return 0;
}

/* Python set of (tx, ty, 0) for tiles that changed. */
static PyObject *sc_tiles_from_mask(const uint8_t *mask, int ntx, int nty) {
    PyObject *set = PySet_New(NULL);
    int tx, ty;
    if (set == NULL) {
        return NULL;
    }
    if (mask == NULL) {
        return set;
    }
    for (tx = 0; tx < ntx; tx++) {
        for (ty = 0; ty < nty; ty++) {
            PyObject *tup;
            if (!mask[(size_t)tx * (size_t)nty + (size_t)ty]) {
                continue;
            }
            tup = Py_BuildValue("(iii)", tx, ty, 0);
            if (tup == NULL) {
                Py_DECREF(set);
                return NULL;
            }
            if (PySet_Add(set, tup) < 0) {
                Py_DECREF(tup);
                Py_DECREF(set);
                return NULL;
            }
            Py_DECREF(tup);
        }
    }
    return set;
}

static int sc_load_profile(PyObject *zs_obj, PyObject *rs_obj, Py_buffer *zs, Py_buffer *rs, ScProfile *profile) {
    if (sc_get_buffer(zs_obj, zs, 0) != 0 || sc_get_buffer(rs_obj, rs, 0) != 0) {
        return -1;
    }
    if (zs->itemsize != (Py_ssize_t)sizeof(double) || rs->itemsize != (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_TypeError, "profile arrays must be float64");
        return -1;
    }
    if (zs->len / (Py_ssize_t)sizeof(double) != rs->len / (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "profile z/r length mismatch");
        return -1;
    }
    sc_profile_prepare(profile, (const double *)zs->buf, (const double *)rs->buf, (int)(zs->len / (Py_ssize_t)sizeof(double)));
    return 0;
}

static int sc_bind_decal(
    PyObject *obj,
    int nx,
    int nv,
    double cell_u,
    double cell_v,
    double origin_u,
    double origin_v,
    int wrap,
    double v_period,
    double v_scale,
    Py_buffer *view,
    ScLaserDecal *out,
    int *present) {
    *present = 0;
    memset(view, 0, sizeof(*view));
    if (obj == NULL || obj == Py_None) {
        return 0;
    }
    if (nx <= 0 || nv <= 0) {
        PyErr_SetString(PyExc_ValueError, "laser map has no cells");
        return -1;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    if ((size_t)view->len < (size_t)nx * (size_t)nv) {
        PyErr_SetString(PyExc_ValueError, "laser buffer is shorter than nx * nv");
        PyBuffer_Release(view);
        memset(view, 0, sizeof(*view));
        return -1;
    }
    out->intensity = (uint8_t *)view->buf;
    out->nx = nx;
    out->nv = nv;
    out->cell_u = cell_u;
    out->cell_v = cell_v;
    out->origin_u = origin_u;
    out->origin_v = origin_v;
    out->wrap_v = wrap;
    out->v_period = v_period;
    out->v_scale = v_scale != 0.0 ? v_scale : 1.0;
    *present = 1;
    return 0;
}

static int sc_bind_flag(PyObject *obj, Py_buffer *view, uint8_t **out) {
    *out = NULL;
    memset(view, 0, sizeof(*view));
    if (obj == NULL || obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    if (view->len < 1) {
        PyErr_SetString(PyExc_ValueError, "laser changed flag is empty");
        PyBuffer_Release(view);
        memset(view, 0, sizeof(*view));
        return -1;
    }
    *out = (uint8_t *)view->buf;
    return 0;
}

static PyObject *py_heightmap(PyObject *self, PyObject *args) {
    PyObject *heights_obj, *p0_obj, *p1_obj, *zs_obj, *rs_obj, *hit_obj, *tile_obj;
    PyObject *laser_obj, *flag_obj;
    int nx, ny, tile, nseg, lnx, lnv, wrap;
    double min_x, min_y, min_z, cell, cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer heights, p0, p1, zs, rs, hit, tiles, laser_buf, flag_buf;
    ScProfile profile;
    ScLaserDecal decal;
    int ntx, nty, rc, have_laser, laser_changed;
    uint8_t *hit_ptr = NULL;
    uint8_t *tile_ptr = NULL;
    uint8_t *flag_ptr = NULL;
    (void)self;
    memset(&heights, 0, sizeof(heights));
    memset(&p0, 0, sizeof(p0));
    memset(&p1, 0, sizeof(p1));
    memset(&zs, 0, sizeof(zs));
    memset(&rs, 0, sizeof(rs));
    memset(&hit, 0, sizeof(hit));
    memset(&tiles, 0, sizeof(tiles));
    memset(&laser_buf, 0, sizeof(laser_buf));
    memset(&flag_buf, 0, sizeof(flag_buf));
    memset(&decal, 0, sizeof(decal));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddiOOOOiiOOOiiddddidO",
            &heights_obj,
            &nx,
            &ny,
            &tile,
            &min_x,
            &min_y,
            &min_z,
            &cell,
            &nseg,
            &p0_obj,
            &p1_obj,
            &zs_obj,
            &rs_obj,
            &ntx,
            &nty,
            &hit_obj,
            &tile_obj,
            &laser_obj,
            &lnx,
            &lnv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &flag_obj)) {
        return NULL;
    }
    if (sc_get_buffer(heights_obj, &heights, 1) != 0) {
        return NULL;
    }
    if (sc_get_buffer(p0_obj, &p0, 0) != 0 || sc_get_buffer(p1_obj, &p1, 0) != 0) {
        goto fail;
    }
    if (sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0) {
        goto fail;
    }
    if (hit_obj != Py_None) {
        if (sc_get_buffer(hit_obj, &hit, 1) != 0) {
            goto fail;
        }
        hit_ptr = (uint8_t *)hit.buf;
    }
    if (tile_obj != Py_None) {
        if (sc_get_buffer(tile_obj, &tiles, 1) != 0) {
            goto fail;
        }
        tile_ptr = (uint8_t *)tiles.buf;
    }
    have_laser = 0;
    laser_changed = 0;
    if (sc_bind_decal(laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, &laser_buf, &decal, &have_laser) != 0) {
        goto fail;
    }
    if (sc_bind_flag(flag_obj, &flag_buf, &flag_ptr) != 0) {
        goto fail;
    }
    /* Drop the GIL so Python can keep running while we carve. */
    Py_BEGIN_ALLOW_THREADS
    rc = sc_heightmap_carve(
        (float *)heights.buf,
        nx,
        ny,
        min_x,
        min_y,
        min_z,
        cell,
        tile,
        (const double *)p0.buf,
        (const double *)p1.buf,
        nseg,
        &profile,
        hit_ptr,
        tile_ptr,
        ntx,
        nty,
        have_laser ? &decal : NULL,
        &laser_changed);
    Py_END_ALLOW_THREADS
    if (rc != 0) {
        PyErr_SetString(PyExc_MemoryError, "heightmap carve failed");
        goto fail;
    }
    if (flag_ptr != NULL) {
        *flag_ptr = laser_changed ? 1 : 0;
    }
    {
        PyObject *dirty = sc_tiles_from_mask(tile_ptr, ntx, nty);
        PyBuffer_Release(&heights);
        PyBuffer_Release(&p0);
        PyBuffer_Release(&p1);
        PyBuffer_Release(&zs);
        PyBuffer_Release(&rs);
        if (hit_ptr) {
            PyBuffer_Release(&hit);
        }
        if (tile_ptr) {
            PyBuffer_Release(&tiles);
        }
        if (laser_buf.buf) {
            PyBuffer_Release(&laser_buf);
        }
        if (flag_buf.buf) {
            PyBuffer_Release(&flag_buf);
        }
        return dirty;
    }
fail:
    if (heights.buf) {
        PyBuffer_Release(&heights);
    }
    if (p0.buf) {
        PyBuffer_Release(&p0);
    }
    if (p1.buf) {
        PyBuffer_Release(&p1);
    }
    if (zs.buf) {
        PyBuffer_Release(&zs);
    }
    if (rs.buf) {
        PyBuffer_Release(&rs);
    }
    if (hit.buf) {
        PyBuffer_Release(&hit);
    }
    if (tiles.buf) {
        PyBuffer_Release(&tiles);
    }
    if (laser_buf.buf) {
        PyBuffer_Release(&laser_buf);
    }
    if (flag_buf.buf) {
        PyBuffer_Release(&flag_buf);
    }
    return NULL;
}

static PyObject *py_cylindrical(PyObject *self, PyObject *args) {
    PyObject *radii_obj, *sin_obj, *cos_obj, *p0_obj, *p1_obj, *a0_obj, *a1_obj, *zs_obj, *rs_obj, *chg_obj, *tile_obj;
    PyObject *laser_obj, *flag_obj;
    int nx, n_theta, tile, nseg, ntx, ntt, lnx, lnv, wrap;
    double min_x, cell, d_theta, axis_y, axis_z, stock_radius;
    double cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer radii, sint, cost, p0, p1, a0, a1, zs, rs, chg, tiles, laser_buf, flag_buf;
    ScProfile profile;
    ScLaserDecal decal;
    int rc, have_laser, laser_changed;
    uint8_t *chg_ptr = NULL;
    uint8_t *tile_ptr = NULL;
    uint8_t *flag_ptr = NULL;
    (void)self;
    memset(&radii, 0, sizeof(radii));
    memset(&sint, 0, sizeof(sint));
    memset(&cost, 0, sizeof(cost));
    memset(&p0, 0, sizeof(p0));
    memset(&p1, 0, sizeof(p1));
    memset(&a0, 0, sizeof(a0));
    memset(&a1, 0, sizeof(a1));
    memset(&zs, 0, sizeof(zs));
    memset(&rs, 0, sizeof(rs));
    memset(&chg, 0, sizeof(chg));
    memset(&tiles, 0, sizeof(tiles));
    memset(&laser_buf, 0, sizeof(laser_buf));
    memset(&flag_buf, 0, sizeof(flag_buf));
    memset(&decal, 0, sizeof(decal));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddddOOiOOOOOOiiOOOiiddddidO",
            &radii_obj,
            &nx,
            &n_theta,
            &tile,
            &min_x,
            &cell,
            &d_theta,
            &axis_y,
            &axis_z,
            &stock_radius,
            &sin_obj,
            &cos_obj,
            &nseg,
            &p0_obj,
            &p1_obj,
            &a0_obj,
            &a1_obj,
            &zs_obj,
            &rs_obj,
            &ntx,
            &ntt,
            &chg_obj,
            &tile_obj,
            &laser_obj,
            &lnx,
            &lnv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &flag_obj)) {
        return NULL;
    }
    if (sc_get_buffer(radii_obj, &radii, 1) != 0) {
        return NULL;
    }
    if (sc_get_buffer(sin_obj, &sint, 0) != 0 || sc_get_buffer(cos_obj, &cost, 0) != 0 || sc_get_buffer(p0_obj, &p0, 0) != 0 ||
        sc_get_buffer(p1_obj, &p1, 0) != 0 || sc_get_buffer(a0_obj, &a0, 0) != 0 || sc_get_buffer(a1_obj, &a1, 0) != 0) {
        goto fail;
    }
    if (sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0) {
        goto fail;
    }
    if (chg_obj != Py_None) {
        if (sc_get_buffer(chg_obj, &chg, 1) != 0) {
            goto fail;
        }
        chg_ptr = (uint8_t *)chg.buf;
    }
    if (tile_obj != Py_None) {
        if (sc_get_buffer(tile_obj, &tiles, 1) != 0) {
            goto fail;
        }
        tile_ptr = (uint8_t *)tiles.buf;
    }
    have_laser = 0;
    laser_changed = 0;
    if (sc_bind_decal(
            laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, &laser_buf, &decal, &have_laser) !=
        0) {
        goto fail;
    }
    if (sc_bind_flag(flag_obj, &flag_buf, &flag_ptr) != 0) {
        goto fail;
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_cylindrical_carve(
        (float *)radii.buf,
        nx,
        n_theta,
        min_x,
        cell,
        d_theta,
        axis_y,
        axis_z,
        stock_radius,
        (const double *)sint.buf,
        (const double *)cost.buf,
        tile,
        (const double *)p0.buf,
        (const double *)p1.buf,
        (const double *)a0.buf,
        (const double *)a1.buf,
        nseg,
        &profile,
        chg_ptr,
        tile_ptr,
        ntx,
        ntt,
        have_laser ? &decal : NULL,
        &laser_changed);
    Py_END_ALLOW_THREADS
    if (rc != 0) {
        PyErr_SetString(PyExc_MemoryError, "cylindrical carve failed");
        goto fail;
    }
    if (flag_ptr != NULL) {
        *flag_ptr = laser_changed ? 1 : 0;
    }
    {
        PyObject *dirty = sc_tiles_from_mask(tile_ptr, ntx, ntt);
        PyBuffer_Release(&radii);
        PyBuffer_Release(&sint);
        PyBuffer_Release(&cost);
        PyBuffer_Release(&p0);
        PyBuffer_Release(&p1);
        PyBuffer_Release(&a0);
        PyBuffer_Release(&a1);
        PyBuffer_Release(&zs);
        PyBuffer_Release(&rs);
        if (chg_ptr) {
            PyBuffer_Release(&chg);
        }
        if (tile_ptr) {
            PyBuffer_Release(&tiles);
        }
        if (laser_buf.buf) {
            PyBuffer_Release(&laser_buf);
        }
        if (flag_buf.buf) {
            PyBuffer_Release(&flag_buf);
        }
        return dirty;
    }
fail:
    if (radii.buf) {
        PyBuffer_Release(&radii);
    }
    if (sint.buf) {
        PyBuffer_Release(&sint);
    }
    if (cost.buf) {
        PyBuffer_Release(&cost);
    }
    if (p0.buf) {
        PyBuffer_Release(&p0);
    }
    if (p1.buf) {
        PyBuffer_Release(&p1);
    }
    if (a0.buf) {
        PyBuffer_Release(&a0);
    }
    if (a1.buf) {
        PyBuffer_Release(&a1);
    }
    if (zs.buf) {
        PyBuffer_Release(&zs);
    }
    if (rs.buf) {
        PyBuffer_Release(&rs);
    }
    if (chg.buf) {
        PyBuffer_Release(&chg);
    }
    if (tiles.buf) {
        PyBuffer_Release(&tiles);
    }
    if (laser_buf.buf) {
        PyBuffer_Release(&laser_buf);
    }
    if (flag_buf.buf) {
        PyBuffer_Release(&flag_buf);
    }
    return NULL;
}

/* Voxel occupancy lives in Python. `keepers` holds the buffers so they are
 * not freed while C is still writing into them.
 */
typedef struct ScVoxelPy2 {
    PyObject *cb;
    PyObject *keepers;
    int failed;
} ScVoxelPy2;

static int sc_py_get_chunk2(void *vctx, int cx, int cy, int cz, uint8_t **data, int *solid, int *was_full) {
    ScVoxelPy2 *ctx = (ScVoxelPy2 *)vctx;
    PyObject *ret;
    Py_buffer view;
    if (ctx->failed) {
        return 0;
    }
    ret = PyObject_CallFunction(ctx->cb, "iii", cx, cy, cz);
    if (ret == NULL) {
        ctx->failed = 1;
        return 0;
    }
    if (ret == Py_None) {
        Py_DECREF(ret);
        return 0; /* empty chunk */
    }
    if (!PyTuple_Check(ret) || PyTuple_GET_SIZE(ret) != 3) {
        Py_DECREF(ret);
        PyErr_SetString(PyExc_TypeError, "voxel chunk callback must return None or (buf, solid, was_full)");
        ctx->failed = 1;
        return 0;
    }
    if (PyObject_GetBuffer(PyTuple_GET_ITEM(ret, 0), &view, PyBUF_WRITABLE | PyBUF_ND) != 0) {
        Py_DECREF(ret);
        ctx->failed = 1;
        return 0;
    }
    *data = (uint8_t *)view.buf;
    *solid = (int)PyLong_AsLong(PyTuple_GET_ITEM(ret, 1));
    *was_full = PyObject_IsTrue(PyTuple_GET_ITEM(ret, 2));
    PyBuffer_Release(&view); /* drop the view; keep the object in `keepers` */
    if (PyList_Append(ctx->keepers, PyTuple_GET_ITEM(ret, 0)) < 0) {
        Py_DECREF(ret);
        ctx->failed = 1;
        return 0;
    }
    Py_DECREF(ret);
    return 1;
}

static PyObject *py_voxel(PyObject *self, PyObject *args) {
    PyObject *p0_obj, *p1_obj, *a0_obj, *a1_obj, *zs_obj, *rs_obj, *cb;
    double min_x, min_y, min_z, voxel;
    int chunk, nx, ny, nz, ncx, ncy, ncz, nseg;
    Py_buffer p0, p1, a0, a1, zs, rs;
    ScProfile profile;
    ScVoxelGrid grid;
    ScVoxelPy2 ctx;
    ScChunkRec *touched = NULL;
    int n_touched = 0;
    int rc, i;
    PyObject *list;
    (void)self;
    memset(&p0, 0, sizeof(p0));
    memset(&p1, 0, sizeof(p1));
    memset(&a0, 0, sizeof(a0));
    memset(&a1, 0, sizeof(a1));
    memset(&zs, 0, sizeof(zs));
    memset(&rs, 0, sizeof(rs));
    if (!PyArg_ParseTuple(
            args,
            "ddddiiiiiiiiOOOOOOO",
            &min_x,
            &min_y,
            &min_z,
            &voxel,
            &chunk,
            &nx,
            &ny,
            &nz,
            &ncx,
            &ncy,
            &ncz,
            &nseg,
            &p0_obj,
            &p1_obj,
            &a0_obj,
            &a1_obj,
            &zs_obj,
            &rs_obj,
            &cb)) {
        return NULL;
    }
    if (!PyCallable_Check(cb)) {
        PyErr_SetString(PyExc_TypeError, "voxel chunk callback must be callable");
        return NULL;
    }
    if (sc_get_buffer(p0_obj, &p0, 0) != 0 || sc_get_buffer(p1_obj, &p1, 0) != 0 || sc_get_buffer(a0_obj, &a0, 0) != 0 ||
        sc_get_buffer(a1_obj, &a1, 0) != 0) {
        goto fail;
    }
    if (sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0) {
        goto fail;
    }
    grid.min_x = min_x;
    grid.min_y = min_y;
    grid.min_z = min_z;
    grid.voxel = voxel;
    grid.chunk = chunk;
    grid.nx = nx;
    grid.ny = ny;
    grid.nz = nz;
    grid.ncx = ncx;
    grid.ncy = ncy;
    grid.ncz = ncz;
    ctx.cb = cb;
    ctx.keepers = PyList_New(0);
    ctx.failed = 0;
    if (ctx.keepers == NULL) {
        goto fail;
    }
    rc = sc_voxel_carve(
        &grid,
        (const double *)p0.buf,
        (const double *)p1.buf,
        (const double *)a0.buf,
        (const double *)a1.buf,
        nseg,
        &profile,
        sc_py_get_chunk2,
        &ctx,
        &touched,
        &n_touched);
    if (ctx.failed || rc != 0) {
        free(touched);
        Py_DECREF(ctx.keepers);
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_RuntimeError, "voxel carve failed");
        }
        goto fail;
    }
    list = PyList_New(n_touched);
    if (list == NULL) {
        free(touched);
        Py_DECREF(ctx.keepers);
        goto fail;
    }
    for (i = 0; i < n_touched; i++) {
        PyObject *item = Py_BuildValue(
            "(iiiiii)", touched[i].cx, touched[i].cy, touched[i].cz, touched[i].solid, touched[i].hits, touched[i].was_full);
        if (item == NULL) {
            Py_DECREF(list);
            free(touched);
            Py_DECREF(ctx.keepers);
            goto fail;
        }
        PyList_SET_ITEM(list, i, item);
    }
    free(touched);
    Py_DECREF(ctx.keepers);
    PyBuffer_Release(&p0);
    PyBuffer_Release(&p1);
    PyBuffer_Release(&a0);
    PyBuffer_Release(&a1);
    PyBuffer_Release(&zs);
    PyBuffer_Release(&rs);
    return list;
fail:
    if (p0.buf) {
        PyBuffer_Release(&p0);
    }
    if (p1.buf) {
        PyBuffer_Release(&p1);
    }
    if (a0.buf) {
        PyBuffer_Release(&a0);
    }
    if (a1.buf) {
        PyBuffer_Release(&a1);
    }
    if (zs.buf) {
        PyBuffer_Release(&zs);
    }
    if (rs.buf) {
        PyBuffer_Release(&rs);
    }
    return NULL;
}

static int sc_bind_f64(PyObject *obj, Py_buffer *view, const double **out, const char *what) {
    memset(view, 0, sizeof(*view));
    *out = NULL;
    if (sc_get_buffer(obj, view, 0) != 0) {
        return -1;
    }
    if (view->itemsize != (Py_ssize_t)sizeof(double)) {
        PyErr_Format(PyExc_TypeError, "%s must be float64", what);
        PyBuffer_Release(view);
        memset(view, 0, sizeof(*view));
        return -1;
    }
    *out = (const double *)view->buf;
    return 0;
}

static PyObject *py_laser_paint(PyObject *self, PyObject *args) {
    PyObject *img_obj, *u0_obj, *v0_obj, *u1_obj, *v1_obj, *burn_obj, *allow_obj, *occ_obj, *zr_obj;
    int nx, nv, wrap, nseg, au0, av0, occ_kind, occ_nx, occ_nv;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    double occ_min_x, occ_min_y, occ_cell, occ_d_theta, occ_period;
    Py_buffer img, u0, v0, u1, v1, burn, allow, occ, zr;
    const double *u0p, *v0p, *u1p, *v1p, *zrp;
    ScLaserDecal map;
    ScLaserOcc occupancy;
    int have_allow, have_occ, changed, rc, allow_rows, allow_cols;
    (void)self;
    memset(&img, 0, sizeof(img));
    memset(&u0, 0, sizeof(u0));
    memset(&v0, 0, sizeof(v0));
    memset(&u1, 0, sizeof(u1));
    memset(&v1, 0, sizeof(v1));
    memset(&burn, 0, sizeof(burn));
    memset(&allow, 0, sizeof(allow));
    memset(&occ, 0, sizeof(occ));
    memset(&zr, 0, sizeof(zr));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOOdOiiiOiidddddO",
            &img_obj,
            &nx,
            &nv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &v_scale,
            &nseg,
            &u0_obj,
            &v0_obj,
            &u1_obj,
            &v1_obj,
            &burn_obj,
            &radius,
            &allow_obj,
            &au0,
            &av0,
            &occ_kind,
            &occ_obj,
            &occ_nx,
            &occ_nv,
            &occ_min_x,
            &occ_min_y,
            &occ_cell,
            &occ_d_theta,
            &occ_period,
            &zr_obj)) {
        return NULL;
    }
    if (sc_bind_decal(img_obj, nx, nv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, v_scale, &img, &map, &rc) != 0) {
        return NULL;
    }
    if (!rc) {
        PyErr_SetString(PyExc_ValueError, "laser paint requires an intensity buffer");
        return NULL;
    }
    if (sc_bind_f64(u0_obj, &u0, &u0p, "u0") != 0 || sc_bind_f64(v0_obj, &v0, &v0p, "v0") != 0 ||
        sc_bind_f64(u1_obj, &u1, &u1p, "u1") != 0 || sc_bind_f64(v1_obj, &v1, &v1p, "v1") != 0) {
        goto fail;
    }
    if (sc_get_buffer(burn_obj, &burn, 0) != 0) {
        goto fail;
    }
    have_allow = 0;
    allow_rows = 0;
    allow_cols = 0;
    if (allow_obj != Py_None) {
        if (sc_get_buffer(allow_obj, &allow, 0) != 0) {
            goto fail;
        }
        if (allow.ndim != 2 || allow.shape == NULL) {
            PyErr_SetString(PyExc_ValueError, "laser allow mask must be a 2D array");
            goto fail;
        }
        allow_rows = (int)allow.shape[0];
        allow_cols = (int)allow.shape[1];
        have_allow = 1;
    }
    have_occ = 0;
    memset(&occupancy, 0, sizeof(occupancy));
    if (occ_kind != 0 && occ_obj != Py_None) {
        if (sc_get_buffer(occ_obj, &occ, 0) != 0) {
            goto fail;
        }
        occupancy.kind = occ_kind;
        occupancy.data = (const float *)occ.buf;
        occupancy.nx = occ_nx;
        occupancy.nv = occ_nv;
        occupancy.min_x = occ_min_x;
        occupancy.min_y = occ_min_y;
        occupancy.cell = occ_cell;
        occupancy.d_theta = occ_d_theta;
        occupancy.period = occ_period;
        have_occ = 1;
    }
        zrp = NULL;
        if (zr_obj != Py_None) {
        if (sc_bind_f64(zr_obj, &zr, &zrp, "z_or_r") != 0) {
            goto fail;
        }
    }
    changed = 0;
    Py_BEGIN_ALLOW_THREADS
    sc_laser_paint(
        &map,
        u0p,
        v0p,
        u1p,
        v1p,
        (const uint8_t *)burn.buf,
        zrp,
        nseg,
        radius,
        have_allow ? (const uint8_t *)allow.buf : NULL,
        au0,
        av0,
        allow_rows,
        allow_cols,
        have_occ ? &occupancy : NULL,
        &changed);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&img);
    PyBuffer_Release(&u0);
    PyBuffer_Release(&v0);
    PyBuffer_Release(&u1);
    PyBuffer_Release(&v1);
    PyBuffer_Release(&burn);
    if (allow.buf) {
        PyBuffer_Release(&allow);
    }
    if (occ.buf) {
        PyBuffer_Release(&occ);
    }
    if (zr.buf) {
        PyBuffer_Release(&zr);
    }
    if (changed) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
fail:
    if (img.buf) {
        PyBuffer_Release(&img);
    }
    if (u0.buf) {
        PyBuffer_Release(&u0);
    }
    if (v0.buf) {
        PyBuffer_Release(&v0);
    }
    if (u1.buf) {
        PyBuffer_Release(&u1);
    }
    if (v1.buf) {
        PyBuffer_Release(&v1);
    }
    if (burn.buf) {
        PyBuffer_Release(&burn);
    }
    if (allow.buf) {
        PyBuffer_Release(&allow);
    }
    if (occ.buf) {
        PyBuffer_Release(&occ);
    }
    if (zr.buf) {
        PyBuffer_Release(&zr);
    }
    return NULL;
}

static PyObject *py_laser_clear(PyObject *self, PyObject *args) {
    PyObject *img_obj, *u0_obj, *v0_obj, *u1_obj, *v1_obj;
    int nx, nv, wrap, nseg;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    Py_buffer img, u0, v0, u1, v1;
    const double *u0p, *v0p, *u1p, *v1p;
    ScLaserDecal map;
    int present, changed;
    (void)self;
    memset(&img, 0, sizeof(img));
    memset(&u0, 0, sizeof(u0));
    memset(&v0, 0, sizeof(v0));
    memset(&u1, 0, sizeof(u1));
    memset(&v1, 0, sizeof(v1));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOd",
            &img_obj,
            &nx,
            &nv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &v_scale,
            &nseg,
            &u0_obj,
            &v0_obj,
            &u1_obj,
            &v1_obj,
            &radius)) {
        return NULL;
    }
    if (sc_bind_decal(img_obj, nx, nv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, v_scale, &img, &map, &present) !=
        0) {
        return NULL;
    }
    if (!present) {
        PyErr_SetString(PyExc_ValueError, "laser clear requires an intensity buffer");
        return NULL;
    }
    if (sc_bind_f64(u0_obj, &u0, &u0p, "u0") != 0 || sc_bind_f64(v0_obj, &v0, &v0p, "v0") != 0 ||
        sc_bind_f64(u1_obj, &u1, &u1p, "u1") != 0 || sc_bind_f64(v1_obj, &v1, &v1p, "v1") != 0) {
        goto fail;
    }
    changed = 0;
    Py_BEGIN_ALLOW_THREADS
    sc_laser_clear_capsules(&map, u0p, v0p, u1p, v1p, nseg, radius, &changed);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&img);
    PyBuffer_Release(&u0);
    PyBuffer_Release(&v0);
    PyBuffer_Release(&u1);
    PyBuffer_Release(&v1);
    if (changed) {
        Py_RETURN_TRUE;
    }
    Py_RETURN_FALSE;
fail:
    if (img.buf) {
        PyBuffer_Release(&img);
    }
    if (u0.buf) {
        PyBuffer_Release(&u0);
    }
    if (v0.buf) {
        PyBuffer_Release(&v0);
    }
    if (u1.buf) {
        PyBuffer_Release(&u1);
    }
    if (v1.buf) {
        PyBuffer_Release(&v1);
    }
    return NULL;
}

static PyMethodDef methods[] = {
    {"heightmap", py_heightmap, METH_VARARGS, "Carve a heightmap batch."},
    {"cylindrical", py_cylindrical, METH_VARARGS, "Carve a cylindrical batch."},
    {"voxel", py_voxel, METH_VARARGS, "Carve a voxel batch."},
    {"laser_paint", py_laser_paint, METH_VARARGS, "Paint laser capsules into a decal."},
    {"laser_clear", py_laser_clear, METH_VARARGS, "Clear laser capsules from a decal."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_stock_carve",
    "Native stock carving kernels.",
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL,
};

PyMODINIT_FUNC PyInit__stock_carve(void) {
    return PyModule_Create(&moduledef);
}
