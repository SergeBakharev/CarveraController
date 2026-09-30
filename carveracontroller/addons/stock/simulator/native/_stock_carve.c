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
    out->dirty = NULL;
    *present = 1;
    return 0;
}

/* Bind optional dirty-index arrays. meta is int32[2]: [n, overflow]. */
static int sc_bind_dirty(
    PyObject *iu_obj,
    PyObject *iv_obj,
    PyObject *meta_obj,
    Py_buffer *iu_view,
    Py_buffer *iv_view,
    Py_buffer *meta_view,
    ScLaserDirty *out,
    int *present) {
    Py_ssize_t cap;
    int32_t *meta;
    *present = 0;
    memset(iu_view, 0, sizeof(*iu_view));
    memset(iv_view, 0, sizeof(*iv_view));
    memset(meta_view, 0, sizeof(*meta_view));
    memset(out, 0, sizeof(*out));
    if (iu_obj == NULL || iu_obj == Py_None || iv_obj == NULL || iv_obj == Py_None || meta_obj == NULL ||
        meta_obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(iu_obj, iu_view, 1) != 0) {
        return -1;
    }
    if (sc_get_buffer(iv_obj, iv_view, 1) != 0) {
        PyBuffer_Release(iu_view);
        memset(iu_view, 0, sizeof(*iu_view));
        return -1;
    }
    if (sc_get_buffer(meta_obj, meta_view, 1) != 0) {
        PyBuffer_Release(iu_view);
        PyBuffer_Release(iv_view);
        memset(iu_view, 0, sizeof(*iu_view));
        memset(iv_view, 0, sizeof(*iv_view));
        return -1;
    }
    if (iu_view->itemsize != (Py_ssize_t)sizeof(int32_t) || iv_view->itemsize != (Py_ssize_t)sizeof(int32_t) ||
        meta_view->itemsize != (Py_ssize_t)sizeof(int32_t)) {
        PyErr_SetString(PyExc_TypeError, "laser dirty buffers must be int32");
        goto fail;
    }
    cap = iu_view->len / (Py_ssize_t)sizeof(int32_t);
    if (cap <= 0 || iv_view->len / (Py_ssize_t)sizeof(int32_t) < cap) {
        PyErr_SetString(PyExc_ValueError, "laser dirty index buffers are empty or mismatched");
        goto fail;
    }
    if (meta_view->len / (Py_ssize_t)sizeof(int32_t) < 2) {
        PyErr_SetString(PyExc_ValueError, "laser dirty meta must hold [n, overflow]");
        goto fail;
    }
    meta = (int32_t *)meta_view->buf;
    out->iu = (int32_t *)iu_view->buf;
    out->iv = (int32_t *)iv_view->buf;
    out->cap = (int)cap;
    out->n = meta[0] > 0 ? (int)meta[0] : 0;
    out->overflow = meta[1] ? 1 : 0;
    if (out->n > out->cap) {
        out->n = out->cap;
        out->overflow = 1;
    }
    *present = 1;
    return 0;
fail:
    if (iu_view->buf) {
        PyBuffer_Release(iu_view);
        memset(iu_view, 0, sizeof(*iu_view));
    }
    if (iv_view->buf) {
        PyBuffer_Release(iv_view);
        memset(iv_view, 0, sizeof(*iv_view));
    }
    if (meta_view->buf) {
        PyBuffer_Release(meta_view);
        memset(meta_view, 0, sizeof(*meta_view));
    }
    return -1;
}

static void sc_dirty_writeback(ScLaserDirty *dirty, Py_buffer *meta_view, int present) {
    int32_t *meta;
    if (!present || meta_view == NULL || meta_view->buf == NULL || dirty == NULL) {
        return;
    }
    meta = (int32_t *)meta_view->buf;
    meta[0] = (int32_t)dirty->n;
    meta[1] = dirty->overflow ? 1 : 0;
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
    PyObject *laser_obj, *flag_obj, *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, ny, tile, nseg, lnx, lnv, wrap;
    double min_x, min_y, min_z, cell, cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer heights, p0, p1, zs, rs, hit, tiles, laser_buf, flag_buf;
    Py_buffer dirty_iu_buf, dirty_iv_buf, dirty_meta_buf;
    ScProfile profile;
    ScLaserDecal decal;
    ScLaserDirty dirty;
    int ntx, nty, rc, have_laser, have_dirty, laser_changed;
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
    memset(&dirty_iu_buf, 0, sizeof(dirty_iu_buf));
    memset(&dirty_iv_buf, 0, sizeof(dirty_iv_buf));
    memset(&dirty_meta_buf, 0, sizeof(dirty_meta_buf));
    memset(&decal, 0, sizeof(decal));
    memset(&dirty, 0, sizeof(dirty));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddiOOOOiiOOOiiddddidOOOO",
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
            &flag_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
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
    have_dirty = 0;
    laser_changed = 0;
    if (sc_bind_decal(laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, &laser_buf, &decal, &have_laser) != 0) {
        goto fail;
    }
    if (sc_bind_flag(flag_obj, &flag_buf, &flag_ptr) != 0) {
        goto fail;
    }
    if (sc_bind_dirty(dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &dirty_iu_buf, &dirty_iv_buf, &dirty_meta_buf, &dirty, &have_dirty) !=
        0) {
        goto fail;
    }
    if (have_laser && have_dirty) {
        decal.dirty = &dirty;
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
    sc_dirty_writeback(&dirty, &dirty_meta_buf, have_dirty);
    if (flag_ptr != NULL) {
        *flag_ptr = laser_changed ? 1 : 0;
    }
    {
        PyObject *out = sc_tiles_from_mask(tile_ptr, ntx, nty);
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
        if (dirty_iu_buf.buf) {
            PyBuffer_Release(&dirty_iu_buf);
        }
        if (dirty_iv_buf.buf) {
            PyBuffer_Release(&dirty_iv_buf);
        }
        if (dirty_meta_buf.buf) {
            PyBuffer_Release(&dirty_meta_buf);
        }
        return out;
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
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
    }
    return NULL;
}

static PyObject *py_cylindrical(PyObject *self, PyObject *args) {
    PyObject *radii_obj, *sin_obj, *cos_obj, *p0_obj, *p1_obj, *a0_obj, *a1_obj, *zs_obj, *rs_obj, *chg_obj, *tile_obj;
    PyObject *laser_obj, *flag_obj, *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, n_theta, tile, nseg, ntx, ntt, lnx, lnv, wrap;
    double min_x, cell, d_theta, axis_y, axis_z, stock_radius;
    double cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer radii, sint, cost, p0, p1, a0, a1, zs, rs, chg, tiles, laser_buf, flag_buf;
    Py_buffer dirty_iu_buf, dirty_iv_buf, dirty_meta_buf;
    ScProfile profile;
    ScLaserDecal decal;
    ScLaserDirty dirty;
    int rc, have_laser, have_dirty, laser_changed;
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
    memset(&dirty_iu_buf, 0, sizeof(dirty_iu_buf));
    memset(&dirty_iv_buf, 0, sizeof(dirty_iv_buf));
    memset(&dirty_meta_buf, 0, sizeof(dirty_meta_buf));
    memset(&decal, 0, sizeof(decal));
    memset(&dirty, 0, sizeof(dirty));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddddOOiOOOOOOiiOOOiiddddidOOOO",
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
            &flag_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
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
    have_dirty = 0;
    laser_changed = 0;
    if (sc_bind_decal(
            laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, &laser_buf, &decal, &have_laser) !=
        0) {
        goto fail;
    }
    if (sc_bind_flag(flag_obj, &flag_buf, &flag_ptr) != 0) {
        goto fail;
    }
    if (sc_bind_dirty(dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &dirty_iu_buf, &dirty_iv_buf, &dirty_meta_buf, &dirty, &have_dirty) !=
        0) {
        goto fail;
    }
    if (have_laser && have_dirty) {
        decal.dirty = &dirty;
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
    sc_dirty_writeback(&dirty, &dirty_meta_buf, have_dirty);
    if (flag_ptr != NULL) {
        *flag_ptr = laser_changed ? 1 : 0;
    }
    {
        PyObject *out = sc_tiles_from_mask(tile_ptr, ntx, ntt);
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
        if (dirty_iu_buf.buf) {
            PyBuffer_Release(&dirty_iu_buf);
        }
        if (dirty_iv_buf.buf) {
            PyBuffer_Release(&dirty_iv_buf);
        }
        if (dirty_meta_buf.buf) {
            PyBuffer_Release(&dirty_meta_buf);
        }
        return out;
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
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
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
    PyObject *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, nv, wrap, nseg, au0, av0, occ_kind, occ_nx, occ_nv;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    double occ_min_x, occ_min_y, occ_cell, occ_d_theta, occ_period;
    Py_buffer img, u0, v0, u1, v1, burn, allow, occ, zr;
    Py_buffer dirty_iu_buf, dirty_iv_buf, dirty_meta_buf;
    const double *u0p, *v0p, *u1p, *v1p, *zrp;
    ScLaserDecal map;
    ScLaserDirty dirty;
    ScLaserOcc occupancy;
    int have_allow, have_occ, have_dirty, changed, rc, allow_rows, allow_cols;
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
    memset(&dirty_iu_buf, 0, sizeof(dirty_iu_buf));
    memset(&dirty_iv_buf, 0, sizeof(dirty_iv_buf));
    memset(&dirty_meta_buf, 0, sizeof(dirty_meta_buf));
    memset(&dirty, 0, sizeof(dirty));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOOdOiiiOiidddddOOOO",
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
            &zr_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
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
    have_dirty = 0;
    if (sc_bind_dirty(dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &dirty_iu_buf, &dirty_iv_buf, &dirty_meta_buf, &dirty, &have_dirty) !=
        0) {
        goto fail;
    }
    if (have_dirty) {
        map.dirty = &dirty;
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
    sc_dirty_writeback(&dirty, &dirty_meta_buf, have_dirty);
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
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
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
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
    }
    return NULL;
}

static PyObject *py_laser_clear(PyObject *self, PyObject *args) {
    PyObject *img_obj, *u0_obj, *v0_obj, *u1_obj, *v1_obj;
    PyObject *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, nv, wrap, nseg;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    Py_buffer img, u0, v0, u1, v1;
    Py_buffer dirty_iu_buf, dirty_iv_buf, dirty_meta_buf;
    const double *u0p, *v0p, *u1p, *v1p;
    ScLaserDecal map;
    ScLaserDirty dirty;
    int present, have_dirty, changed;
    (void)self;
    memset(&img, 0, sizeof(img));
    memset(&u0, 0, sizeof(u0));
    memset(&v0, 0, sizeof(v0));
    memset(&u1, 0, sizeof(u1));
    memset(&v1, 0, sizeof(v1));
    memset(&dirty_iu_buf, 0, sizeof(dirty_iu_buf));
    memset(&dirty_iv_buf, 0, sizeof(dirty_iv_buf));
    memset(&dirty_meta_buf, 0, sizeof(dirty_meta_buf));
    memset(&dirty, 0, sizeof(dirty));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOdOOO",
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
            &radius,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
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
    have_dirty = 0;
    if (sc_bind_dirty(dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &dirty_iu_buf, &dirty_iv_buf, &dirty_meta_buf, &dirty, &have_dirty) !=
        0) {
        goto fail;
    }
    if (have_dirty) {
        map.dirty = &dirty;
    }
    changed = 0;
    Py_BEGIN_ALLOW_THREADS
    sc_laser_clear_capsules(&map, u0p, v0p, u1p, v1p, nseg, radius, &changed);
    Py_END_ALLOW_THREADS
    sc_dirty_writeback(&dirty, &dirty_meta_buf, have_dirty);
    PyBuffer_Release(&img);
    PyBuffer_Release(&u0);
    PyBuffer_Release(&v0);
    PyBuffer_Release(&u1);
    PyBuffer_Release(&v1);
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
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
    if (dirty_iu_buf.buf) {
        PyBuffer_Release(&dirty_iu_buf);
    }
    if (dirty_iv_buf.buf) {
        PyBuffer_Release(&dirty_iv_buf);
    }
    if (dirty_meta_buf.buf) {
        PyBuffer_Release(&dirty_meta_buf);
    }
    return NULL;
}

static PyObject *sc_batch_to_list(ScMeshBatch *batch) {
    PyObject *list = PyList_New(batch->nparts);
    int i;
    if (list == NULL) {
        return NULL;
    }
    for (i = 0; i < batch->nparts; i++) {
        ScMeshPart *part = &batch->parts[i];
        PyObject *verts = PyBytes_FromStringAndSize(
            (const char *)part->verts, (Py_ssize_t)part->nverts * 12 * (Py_ssize_t)sizeof(float));
        PyObject *indices = PyBytes_FromStringAndSize(
            (const char *)part->indices, (Py_ssize_t)part->nindices * (Py_ssize_t)sizeof(uint16_t));
        PyObject *item;
        if (verts == NULL || indices == NULL) {
            Py_XDECREF(verts);
            Py_XDECREF(indices);
            Py_DECREF(list);
            return NULL;
        }
        item = PyTuple_Pack(2, verts, indices);
        Py_DECREF(verts);
        Py_DECREF(indices);
        if (item == NULL) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(list, i, item);
    }
    return list;
}

static PyObject *py_mesh_heightmap(PyObject *self, PyObject *args) {
    PyObject *patch_obj;
    Py_buffer patch;
    int gw, gh, x0, y0, nx, ny;
    double ox, oy, min_z, cell, cr, cg, cb, ca;
    ScMeshBatch batch;
    PyObject *list;
    int rc;
    (void)self;
    memset(&patch, 0, sizeof(patch));
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args,
            "Oiiiiiidddddddd",
            &patch_obj,
            &gw,
            &gh,
            &x0,
            &y0,
            &nx,
            &ny,
            &ox,
            &oy,
            &min_z,
            &cell,
            &cr,
            &cg,
            &cb,
            &ca)) {
        return NULL;
    }
    if (sc_get_buffer(patch_obj, &patch, 0) != 0) {
        return NULL;
    }
    if (gw < 0 || gh < 0 || patch.len < (Py_ssize_t)(gw + 2) * (gh + 2) * (Py_ssize_t)sizeof(float)) {
        PyErr_SetString(PyExc_ValueError, "heightmap patch is smaller than the halo");
        PyBuffer_Release(&patch);
        return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_heightmap(
        (const float *)patch.buf, gw, gh, x0, y0, nx, ny, ox, oy, min_z, cell, cr, cg, cb, ca, &batch);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&patch);
    if (rc != 0) {
        sc_mesh_batch_free(&batch);
        return PyErr_NoMemory();
    }
    list = sc_batch_to_list(&batch);
    sc_mesh_batch_free(&batch);
    return list;
}

static PyObject *py_mesh_cylinder(PyObject *self, PyObject *args) {
    PyObject *radii_obj, *sin_obj, *cos_obj;
    Py_buffer radii, sint, cost;
    int nx, n_theta, ix0, nx_total;
    double min_x, cell, ay, az, floor_r, cr, cg, cb, ca;
    ScMeshBatch batch;
    PyObject *list;
    int rc;
    (void)self;
    memset(&radii, 0, sizeof(radii));
    memset(&sint, 0, sizeof(sint));
    memset(&cost, 0, sizeof(cost));
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args,
            "OiiiiddddOOddddd",
            &radii_obj,
            &nx,
            &n_theta,
            &ix0,
            &nx_total,
            &min_x,
            &cell,
            &ay,
            &az,
            &sin_obj,
            &cos_obj,
            &floor_r,
            &cr,
            &cg,
            &cb,
            &ca)) {
        return NULL;
    }
    if (sc_get_buffer(radii_obj, &radii, 0) != 0) {
        return NULL;
    }
    if (sc_get_buffer(sin_obj, &sint, 0) != 0 || sc_get_buffer(cos_obj, &cost, 0) != 0) {
        PyBuffer_Release(&radii);
        if (sint.buf) {
            PyBuffer_Release(&sint);
        }
        return NULL;
    }
    if (nx < 0 || n_theta < 0 || radii.len < (Py_ssize_t)nx * n_theta * (Py_ssize_t)sizeof(float) ||
        sint.len < (Py_ssize_t)n_theta * (Py_ssize_t)sizeof(double) ||
        cost.len < (Py_ssize_t)n_theta * (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "cylindrical mesh buffers are the wrong size");
        PyBuffer_Release(&radii);
        PyBuffer_Release(&sint);
        PyBuffer_Release(&cost);
        return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_cylinder(
        (const float *)radii.buf,
        nx,
        n_theta,
        ix0,
        nx_total,
        min_x,
        cell,
        ay,
        az,
        (const double *)sint.buf,
        (const double *)cost.buf,
        floor_r,
        cr,
        cg,
        cb,
        ca,
        &batch);
    Py_END_ALLOW_THREADS
    PyBuffer_Release(&radii);
    PyBuffer_Release(&sint);
    PyBuffer_Release(&cost);
    if (rc != 0) {
        sc_mesh_batch_free(&batch);
        return PyErr_NoMemory();
    }
    list = sc_batch_to_list(&batch);
    sc_mesh_batch_free(&batch);
    return list;
}

static PyObject *py_mesh_voxel(PyObject *self, PyObject *args) {
    PyObject *occ_obj, *valid_obj, *modes_obj, *faces_obj;
    Py_buffer occ, valid, face_views[6];
    int face_mode[6];
    const uint8_t *face_ptr[6];
    int cs, i, rc;
    double ox, oy, oz, vs, cr, cg, cb, ca;
    ScMeshBatch batch;
    PyObject *list;
    (void)self;
    memset(&occ, 0, sizeof(occ));
    memset(&valid, 0, sizeof(valid));
    memset(face_views, 0, sizeof(face_views));
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args, "OOiOOdddddddd", &occ_obj, &valid_obj, &cs, &modes_obj, &faces_obj, &ox, &oy, &oz, &vs, &cr, &cg, &cb, &ca)) {
        return NULL;
    }
    if (cs <= 0) {
        PyErr_SetString(PyExc_ValueError, "voxel chunk size must be positive");
        return NULL;
    }
    if (occ_obj != Py_None && sc_get_buffer(occ_obj, &occ, 0) != 0) {
        return NULL;
    }
    if (valid_obj != Py_None && sc_get_buffer(valid_obj, &valid, 0) != 0) {
        if (occ.buf) {
            PyBuffer_Release(&occ);
        }
        return NULL;
    }
    if (!PySequence_Check(modes_obj) || !PySequence_Check(faces_obj) || PySequence_Size(modes_obj) != 6 ||
        PySequence_Size(faces_obj) != 6) {
        PyErr_SetString(PyExc_ValueError, "voxel mesh expects 6 face modes and 6 faces");
        goto fail;
    }
    for (i = 0; i < 6; i++) {
        PyObject *mode_obj = PySequence_GetItem(modes_obj, i);
        PyObject *face_obj = PySequence_GetItem(faces_obj, i);
        long mode;
        if (mode_obj == NULL || face_obj == NULL) {
            Py_XDECREF(mode_obj);
            Py_XDECREF(face_obj);
            goto fail;
        }
        mode = PyLong_AsLong(mode_obj);
        Py_DECREF(mode_obj);
        if (mode < 0 || mode > 2) {
            Py_DECREF(face_obj);
            PyErr_SetString(PyExc_ValueError, "voxel face mode must be 0, 1, or 2");
            goto fail;
        }
        face_mode[i] = (int)mode;
        face_ptr[i] = NULL;
        if (mode == 2) {
            if (sc_get_buffer(face_obj, &face_views[i], 0) != 0) {
                Py_DECREF(face_obj);
                face_views[i].buf = NULL;
                goto fail;
            }
            if (face_views[i].len < (Py_ssize_t)cs * cs) {
                Py_DECREF(face_obj);
                PyErr_SetString(PyExc_ValueError, "voxel face is smaller than the chunk");
                goto fail;
            }
            face_ptr[i] = (const uint8_t *)face_views[i].buf;
        }
        Py_DECREF(face_obj);
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_voxel_chunk(
        occ.buf ? (const uint8_t *)occ.buf : NULL,
        valid.buf ? (const uint8_t *)valid.buf : NULL,
        cs,
        face_mode,
        face_ptr,
        ox,
        oy,
        oz,
        vs,
        cr,
        cg,
        cb,
        ca,
        &batch);
    Py_END_ALLOW_THREADS
    for (i = 0; i < 6; i++) {
        if (face_views[i].buf) {
            PyBuffer_Release(&face_views[i]);
            face_views[i].buf = NULL;
        }
    }
    if (occ.buf) {
        PyBuffer_Release(&occ);
    }
    if (valid.buf) {
        PyBuffer_Release(&valid);
    }
    if (rc != 0) {
        sc_mesh_batch_free(&batch);
        return PyErr_NoMemory();
    }
    list = sc_batch_to_list(&batch);
    sc_mesh_batch_free(&batch);
    return list;
fail:
    for (i = 0; i < 6; i++) {
        if (face_views[i].buf) {
            PyBuffer_Release(&face_views[i]);
        }
    }
    if (occ.buf) {
        PyBuffer_Release(&occ);
    }
    if (valid.buf) {
        PyBuffer_Release(&valid);
    }
    sc_mesh_batch_free(&batch);
    return NULL;
}

static PyMethodDef methods[] = {
    {"heightmap", py_heightmap, METH_VARARGS, "Carve a heightmap batch."},
    {"cylindrical", py_cylindrical, METH_VARARGS, "Carve a cylindrical batch."},
    {"voxel", py_voxel, METH_VARARGS, "Carve a voxel batch."},
    {"laser_paint", py_laser_paint, METH_VARARGS, "Paint laser capsules into a decal."},
    {"laser_clear", py_laser_clear, METH_VARARGS, "Clear laser capsules from a decal."},
    {"mesh_heightmap", py_mesh_heightmap, METH_VARARGS, "Weld a heightmap window into Kivy meshes."},
    {"mesh_cylinder", py_mesh_cylinder, METH_VARARGS, "Weld a cylindrical shell into Kivy meshes."},
    {"mesh_voxel", py_mesh_voxel, METH_VARARGS, "Greedy-mesh one voxel chunk."},
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
