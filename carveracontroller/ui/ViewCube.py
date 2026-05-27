"""
Orientation view cube helper for the GCode Viewer.
"""

import math

from kivy.graphics.transformation import Matrix

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
# At poles (|m_xRot| == 90) m_yRot rolls the view around Z; explicit values keep faces axis-aligned.
# Top/bottom use opposite m_yRot so +X stays to the right on screen for both poles.
VIEW_FACE_PRESETS = {
    FACE_POS_X: (0.0, 270.0),
    FACE_NEG_X: (0.0, 90.0),
    FACE_POS_Y: (0.0, 0.0),
    FACE_NEG_Y: (0.0, 180.0),
    FACE_POS_Z: (90.0, 180.0),
    FACE_NEG_Z: (-90.0, 0.0),
}

_FACE_NORMALS = {
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
]

HALF = 0.5


def _face_uv_corners(u0, v0, u1, v1, flip_u=False):
    # Flip V: PNG/image editors use top-left origin; GL samples with v=0 at bottom.
    if flip_u:
        u0, u1 = u1, u0
    return [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]


def build_mesh():
    """Return (vertices, indices) for a unit cube with per-face atlas UVs."""
    faces = [
        (FACE_POS_X, (+HALF, -HALF, -HALF), (+HALF, +HALF, -HALF), (+HALF, +HALF, +HALF), (+HALF, -HALF, +HALF), (1.0, 0.0, 0.0)),
        (FACE_NEG_X, (-HALF, +HALF, -HALF), (-HALF, -HALF, -HALF), (-HALF, -HALF, +HALF), (-HALF, +HALF, +HALF), (-1.0, 0.0, 0.0)),
        (FACE_POS_Y, (-HALF, +HALF, -HALF), (+HALF, +HALF, -HALF), (+HALF, +HALF, +HALF), (-HALF, +HALF, +HALF), (0.0, 1.0, 0.0)),
        (FACE_NEG_Y, (+HALF, -HALF, -HALF), (-HALF, -HALF, -HALF), (-HALF, -HALF, +HALF), (+HALF, -HALF, +HALF), (0.0, -1.0, 0.0)),
        (FACE_POS_Z, (-HALF, -HALF, +HALF), (+HALF, -HALF, +HALF), (+HALF, +HALF, +HALF), (-HALF, +HALF, +HALF), (0.0, 0.0, 1.0)),
        (FACE_NEG_Z, (+HALF, -HALF, -HALF), (-HALF, -HALF, -HALF), (-HALF, +HALF, -HALF), (+HALF, +HALF, -HALF), (0.0, 0.0, -1.0)),
    ]

    vertices = []
    indices = []
    for face_id, p0, p1, p2, p3, normal in faces:
        u0, v0, u1, v1 = ATLAS_UV[face_id]
        flip_u = face_id in (FACE_POS_Y, FACE_NEG_Y)
        uvs = _face_uv_corners(u0, v0, u1, v1, flip_u=flip_u)
        corners = (p0, p1, p2, p3)
        base = len(vertices) // 8
        for corner, uv in zip(corners, uvs):
            vertices.extend([
                corner[0], corner[1], corner[2],
                normal[0], normal[1], normal[2],
                uv[0], uv[1],
            ])
        indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

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
    half = float(cube_scale) * 0.5
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
        (FACE_POS_X, 0, half),
        (FACE_NEG_X, 0, -half),
        (FACE_POS_Y, 1, half),
        (FACE_NEG_Y, 1, -half),
        (FACE_POS_Z, 2, half),
        (FACE_NEG_Z, 2, -half),
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
        if abs(coords[u]) > half + 1e-5 or abs(coords[v]) > half + 1e-5:
            continue

        nx, ny, nz = _FACE_NORMALS[face_id]
        if nx * dx + ny * dy + nz * dz >= -1e-6:
            continue

        best_t = t
        best_face = face_id

    return best_face


def apply_face_preset(face_id, current_x_rot, current_y_rot):
    """Return (m_xRot, m_yRot) after snapping to a face preset."""
    return VIEW_FACE_PRESETS[face_id]
