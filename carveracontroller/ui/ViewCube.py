"""
Orientation view cube helper for the GCode Viewer.
"""

import math
import os

from kivy.graphics.transformation import Matrix

from ..Objloader import ObjFile

FACE_POS_X = 'pos_x'
FACE_NEG_X = 'neg_x'
FACE_POS_Y = 'pos_y'
FACE_NEG_Y = 'neg_y'
FACE_POS_Z = 'pos_z'
FACE_NEG_Z = 'neg_z'

# Normalized UV rects (u0, v0, u1, v1) — Kivy texture origin is bottom-left.
ATLAS_UV = {
    FACE_POS_X: (0.0, 2.0 / 3.0, 0.5, 1.0),
    FACE_NEG_X: (0.5, 2.0 / 3.0, 1.0, 1.0),
    FACE_POS_Y: (0.0, 1.0 / 3.0, 0.5, 2.0 / 3.0),
    FACE_NEG_Y: (0.5, 1.0 / 3.0, 1.0, 2.0 / 3.0),
    FACE_POS_Z: (0.0, 0.0, 0.5, 1.0 / 3.0),
    FACE_NEG_Z: (0.5, 0.0, 1.0, 1.0 / 3.0),
}

# Camera orbit presets: (m_xRot, m_yRot).
VIEW_FACE_PRESETS = {
    FACE_POS_X: (0.0, 270.0),
    FACE_NEG_X: (0.0, 90.0),
    FACE_POS_Y: (0.0, 0.0),
    FACE_NEG_Y: (0.0, 180.0),
    FACE_POS_Z: (90.0, 180.0),
    FACE_NEG_Z: (-90.0, 0.0),
}

FACE_NORMALS = {
    FACE_POS_X: (+1.0, 0.0, 0.0),
    FACE_NEG_X: (-1.0, 0.0, 0.0),
    FACE_POS_Y: (0.0, +1.0, 0.0),
    FACE_NEG_Y: (0.0, -1.0, 0.0),
    FACE_POS_Z: (0.0, 0.0, +1.0),
    FACE_NEG_Z: (0.0, 0.0, -1.0),
}

VERTEX_FORMAT = [
    (b'v_pos', 3, 'float'),
    (b'v_normal', 3, 'float'),
    (b'v_tc0', 2, 'float'),
    (b'v_uv_bounds', 4, 'float'),
]

# 3 pos + 3 normal + 2 uv + 4 uv bounds = 12
VERTEX_STRIDE = 12

def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _face_param(coord):
    """Map a face tangent coordinate from [-1, 1] to [0, 1]"""
    return (coord + 1.0) * 0.5


def _face_id_from_normal(nx, ny, nz, x, y, z):
    """Dominant face from normal; position breaks ties on 45° chamfers."""
    ax, ay, az = abs(nx), abs(ny), abs(nz)
    if abs(ax - ay) < 1e-4 and az < max(ax, ay) - 1e-4:
        return _face_id_from_position(x, y, z)
    if abs(ax - az) < 1e-4 and ay < max(ax, az) - 1e-4:
        return _face_id_from_position(x, y, z)
    if abs(ay - az) < 1e-4 and ax < max(ay, az) - 1e-4:
        return _face_id_from_position(x, y, z)
    if ax >= ay and ax >= az:
        return FACE_POS_X if nx > 0 else FACE_NEG_X
    if ay >= ax and ay >= az:
        return FACE_POS_Y if ny > 0 else FACE_NEG_Y
    return FACE_POS_Z if nz > 0 else FACE_NEG_Z


def _face_id_from_position(x, y, z):
    ax, ay, az = abs(x), abs(y), abs(z)
    if ax >= ay and ax >= az:
        return FACE_POS_X if x > 0 else FACE_NEG_X
    if ay >= ax and ay >= az:
        return FACE_POS_Y if y > 0 else FACE_NEG_Y
    return FACE_POS_Z if z > 0 else FACE_NEG_Z


def _project_on_face(face_id, x, y, z):
    """Snap chamfer verts to the parent face plane so UVs stay in one atlas tile."""
    if face_id == FACE_POS_X:
        return 1.0, _clamp(y, -1.0, 1.0), _clamp(z, -1.0, 1.0)
    if face_id == FACE_NEG_X:
        return -1.0, _clamp(y, -1.0, 1.0), _clamp(z, -1.0, 1.0)
    if face_id == FACE_POS_Y:
        return _clamp(x, -1.0, 1.0), 1.0, _clamp(z, -1.0, 1.0)
    if face_id == FACE_NEG_Y:
        return _clamp(x, -1.0, 1.0), -1.0, _clamp(z, -1.0, 1.0)
    if face_id == FACE_POS_Z:
        return _clamp(x, -1.0, 1.0), _clamp(y, -1.0, 1.0), 1.0
    return _clamp(x, -1.0, 1.0), _clamp(y, -1.0, 1.0), -1.0


def _uv_bounds_for_face(face_id):
    u0, v0, u1, v1 = ATLAS_UV[face_id]
    return u0, v0, u1, v1


def _triangle_face_id(x0, y0, z0, x1, y1, z1, x2, y2, z2):
    ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
    vx, vy, vz = x2 - x0, y2 - y0, z2 - z0
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    cx, cy, cz = (x0 + x1 + x2) / 3.0, (y0 + y1 + y2) / 3.0, (z0 + z1 + z2) / 3.0
    return _face_id_from_normal(nx, ny, nz, cx, cy, cz)


def _atlas_uv_for_vertex(face_id, x, y, z):
    """Map a point on the unit cube to atlas UVs (matches legacy build_mesh layout)."""
    u0, v0, u1, v1 = ATLAS_UV[face_id]
    if face_id == FACE_POS_X:
        u = u0 + (u1 - u0) * _face_param(y)
        v = v1 + (v0 - v1) * _face_param(z)
    elif face_id == FACE_NEG_X:
        u = u0 + (u1 - u0) * (1.0 - _face_param(y))
        v = v1 + (v0 - v1) * _face_param(z)
    elif face_id == FACE_POS_Y:
        u = u1 + (u0 - u1) * _face_param(x)
        v = v1 + (v0 - v1) * _face_param(z)
    elif face_id == FACE_NEG_Y:
        u = u1 + (u0 - u1) * (1.0 - _face_param(x))
        v = v1 + (v0 - v1) * _face_param(z)
    elif face_id == FACE_POS_Z:
        u = u0 + (u1 - u0) * _face_param(x)
        v = v1 + (v0 - v1) * _face_param(y)
    else:  # FACE_NEG_Z
        u = u0 + (u1 - u0) * (1.0 - _face_param(x))
        v = v1 + (v0 - v1) * _face_param(y)
    return _clamp(u, u0, u1), _clamp(v, v0, v1)


def _write_vertex(vertices, slot, x, y, z, nx, ny, nz, u, v, bounds):
    i = slot * VERTEX_STRIDE
    vertices[i:i + 12] = [
        x, y, z, nx, ny, nz, u, v,
        bounds[0], bounds[1], bounds[2], bounds[3],
    ]


def _remap_atlas_uvs(vertices, indices):
    """One atlas tile per triangle so chamfer tris do not interpolate across seams."""
    stride = VERTEX_STRIDE
    for t in range(0, len(indices), 3):
        slots = (indices[t], indices[t + 1], indices[t + 2])
        coords = []
        for slot in slots:
            i = slot * stride
            coords.append((
                vertices[i], vertices[i + 1], vertices[i + 2],
                vertices[i + 3], vertices[i + 4], vertices[i + 5],
            ))
        face_id = _triangle_face_id(*coords[0][:3], *coords[1][:3], *coords[2][:3])
        bounds = _uv_bounds_for_face(face_id)
        for slot, (x, y, z, nx, ny, nz) in zip(slots, coords):
            px, py, pz = _project_on_face(face_id, x, y, z)
            u, v = _atlas_uv_for_vertex(face_id, px, py, pz)
            _write_vertex(vertices, slot, x, y, z, nx, ny, nz, u, v, bounds)


def load_mesh(obj_path):
    """Load view-cube geometry from a Wavefront OBJ (vertices, indices)."""
    if not os.path.isfile(obj_path):
        raise FileNotFoundError(obj_path)
    obj = ObjFile(obj_path)
    if not obj.objects:
        raise ValueError(f'no meshes in {obj_path}')
    mesh = next(iter(obj.objects.values()))
    indices = list(mesh.indices)
    # ObjFile uses 8 floats/vert; expand to our stride before remapping UVs.
    src_stride = 8
    vertices = [0.0] * (len(mesh.vertices) // src_stride * VERTEX_STRIDE)
    for slot in range(len(mesh.vertices) // src_stride):
        si, di = slot * src_stride, slot * VERTEX_STRIDE
        vertices[di:di + 8] = mesh.vertices[si:si + 8]
    _remap_atlas_uvs(vertices, indices)
    return vertices, indices


def _model_matrix(cube_scale):
    scale = Matrix()
    scale[0] = float(cube_scale)
    scale[5] = float(cube_scale)
    scale[10] = float(cube_scale)
    return scale


def pick_face(ndc_x, ndc_y, view_mat, proj_mat, cube_scale):
    """
    Pick the cube face under an NDC point in the HUD viewport.

    Casts a ray through the click and returns the nearest axis-aligned face
    hit within the cube bounds (same transform chain as the draw shader).
    """
    # We undo cube_scale below, so the ray ends up in the cube's own coordinates
    # where each face is 1.0 away from the center.
    half_extent = 1.0
    model = _model_matrix(cube_scale)
    mvp = proj_mat.multiply(view_mat).multiply(model)
    inv = mvp.inverse()
    if inv is None:
        return FACE_POS_Y

    near = inv.transform_point(ndc_x, ndc_y, -1.0)
    far = inv.transform_point(ndc_x, ndc_y, 1.0)
    ox, oy, oz = near[0], near[1], near[2]
    dx, dy, dz = far[0] - ox, far[1] - oy, far[2] - oz
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-9:
        return FACE_POS_Y
    dx, dy, dz = dx / length, dy / length, dz / length

    planes = (
        (FACE_POS_X, 0, half_extent),
        (FACE_NEG_X, 0, -half_extent),
        (FACE_POS_Y, 1, half_extent),
        (FACE_NEG_Y, 1, -half_extent),
        (FACE_POS_Z, 2, half_extent),
        (FACE_NEG_Z, 2, -half_extent),
    )

    best_t = float('inf')
    best_face = FACE_POS_Y

    for face_id, axis, plane in planes:
        origin = (ox, oy, oz)[axis]
        direction = (dx, dy, dz)[axis]
        if abs(direction) < 1e-9:
            continue
        t = (plane - origin) / direction
        if t <= 1e-6 or t >= best_t:
            continue

        px = ox + t * dx
        py = oy + t * dy
        pz = oz + t * dz
        coords = (px, py, pz)
        u = (axis + 1) % 3
        v = (axis + 2) % 3
        if abs(coords[u]) > half_extent + 1e-5 or abs(coords[v]) > half_extent + 1e-5:
            continue

        nx, ny, nz = FACE_NORMALS[face_id]
        if nx * dx + ny * dy + nz * dz >= -1e-6:
            continue

        best_t = t
        best_face = face_id

    return best_face


def apply_face_preset(face_id, current_x_rot, current_y_rot):
    """Return (m_xRot, m_yRot) after snapping to a face preset."""
    return VIEW_FACE_PRESETS[face_id]
