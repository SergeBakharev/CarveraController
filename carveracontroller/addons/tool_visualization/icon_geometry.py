"""Build 2D silhouette geometry for tool toolbar / tooltip icons.

Pure math (no Kivy). Reuses ``_tool_profile_with_shank`` from the mesh
builder so icons match the 3D tool shapes. Output is triangle lists and an
outline polyline in a unit square (or unit rectangle), ready for Kivy Mesh
drawing or CPU rasterization into a tooltip texture.
"""

from __future__ import annotations

from carveracontroller.addons.tool_visualization.mesh_builder import _tool_profile_with_shank

# Fraction of the crop box reserved as empty margin on each side.
_PADDING = 0.08

# Thumb (toolbar): tight crop on the cutting end.
_THUMB_CROP_TIP_FACTOR = 1.15
_THUMB_CROP_MIN_DIAMETERS = 1.0
_THUMB_CROP_MAX_DIAMETERS = 3.0

# Body (tooltip): show the flutes plus a clear shank stub above them.
_BODY_SHANK_EXTRA_DIAMETERS = 1.75
_BODY_CROP_MIN_DIAMETERS = 2.75
_BODY_CROP_MAX_DIAMETERS = 5.5

FRAMING_THUMB = "thumb"
FRAMING_BODY = "body"


def _interpolate_radius(profile, z_target):
    """Linearly interpolate radius at ``z_target`` along a sorted profile."""
    if not profile:
        return 0.0
    if z_target <= profile[0][0]:
        return profile[0][1]
    if z_target >= profile[-1][0]:
        return profile[-1][1]

    for i in range(len(profile) - 1):
        z0, r0 = profile[i]
        z1, r1 = profile[i + 1]
        if z0 <= z_target <= z1:
            if abs(z1 - z0) < 1e-12:
                return r1
            t = (z_target - z0) / (z1 - z0)
            return r0 + t * (r1 - r0)
    return profile[-1][1]


def _tip_end_z(profile, shank_start):
    """First z where the flute portion reaches its maximum cutting radius."""
    flute_end = min(shank_start, len(profile))
    if flute_end <= 0:
        flute_end = len(profile)
    flute = profile[:flute_end]
    if not flute:
        return profile[0][0] if profile else 0.0

    max_r = max(r for _z, r in flute)
    for z, r in flute:
        if r >= max_r - 1e-9:
            return z
    return flute[-1][0]


def _flute_end_z(profile, shank_start):
    """Z of the last flute ring (the point just before the shank starts)."""
    if shank_start <= 0:
        return profile[0][0] if profile else 0.0
    if shank_start >= len(profile):
        return profile[-1][0] if profile else 0.0
    return profile[shank_start - 1][0]


def _crop_z(profile, shank_start, framing=FRAMING_THUMB):
    """Choose the axial crop for an icon silhouette.

    ``framing="thumb"`` keeps a tight tip crop for small toolbar buttons.
    ``framing="body"`` keeps more stick-out so the shank reads in tooltips.
    """
    if not profile:
        return 0.0

    overall_z = profile[-1][0]
    max_r = max((r for _z, r in profile), default=0.0)
    outer_diameter = max(max_r * 2.0, 1e-6)

    tip_z = _tip_end_z(profile, shank_start)
    flute_z = _flute_end_z(profile, shank_start)

    if framing == FRAMING_BODY:
        target = max(flute_z + _BODY_SHANK_EXTRA_DIAMETERS * outer_diameter, tip_z + 2.5 * outer_diameter)
        lower = _BODY_CROP_MIN_DIAMETERS * outer_diameter
        upper = min(overall_z, _BODY_CROP_MAX_DIAMETERS * outer_diameter)
    else:
        target = _THUMB_CROP_TIP_FACTOR * max(tip_z, flute_z)
        lower = _THUMB_CROP_MIN_DIAMETERS * outer_diameter
        upper = min(overall_z, _THUMB_CROP_MAX_DIAMETERS * outer_diameter)

    if upper < lower:
        return overall_z
    return min(max(target, lower), upper)


def _crop_profile(profile, shank_start, z_crop):
    """Keep points with z <= z_crop, interpolating a final ring at the cut.

    Returns ``(cropped_profile, cropped_shank_start)``.
    """
    if not profile:
        return [], 0

    if z_crop >= profile[-1][0] - 1e-12:
        return list(profile), shank_start

    cropped = []
    for z, r in profile:
        if z <= z_crop + 1e-12:
            cropped.append((z, r))
        else:
            break

    n_kept = len(cropped)
    if n_kept == 0:
        # Crop is before the tip — keep a stub at the tip.
        return [profile[0]], 0

    if abs(cropped[-1][0] - z_crop) > 1e-9:
        cropped.append((z_crop, _interpolate_radius(profile, z_crop)))

    # Map the original shank boundary onto the cropped list. Segments with
    # start index >= cropped_shank are shank-colored.
    if shank_start >= len(profile) or shank_start >= n_kept:
        # Cut is entirely within the flute (or the whole tool was flute).
        cropped_shank = len(cropped)
    else:
        cropped_shank = shank_start

    return cropped, cropped_shank


def _normalize_points(points, padding=_PADDING, box_aspect=1.0):
    """Map ``(x, z)`` silhouette points into a padded unit rectangle.

    Tip is at the bottom (small y). Aspect is preserved. ``box_aspect`` is the
    output width/height ratio: points are still returned in ``[0, 1] x [0, 1]``
    UV space, but scaling accounts for non-square display so the silhouette
    is not stretched when drawn into a tall tooltip texture.
    """
    if not points:
        return []

    xs = [p[0] for p in points]
    zs = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    span_x = max(max_x - min_x, 1e-9)
    span_z = max(max_z - min_z, 1e-9)

    box_aspect = max(box_aspect, 1e-6)
    usable_w = (1.0 - 2.0 * padding) * box_aspect
    usable_h = 1.0 - 2.0 * padding
    # Isotropic scale in "height-normalized" units (y spans 0..1 of the box).
    scale = min(usable_w / span_x, usable_h / span_z)

    # Center in the box. Convert isotropic x back to UV via / box_aspect.
    center_x = (min_x + max_x) / 2.0
    center_z = (min_z + max_z) / 2.0
    offset_x = 0.5 - (scale * center_x) / box_aspect
    offset_y = 0.5 - scale * center_z

    return [(offset_x + (scale * x) / box_aspect, offset_y + scale * z) for x, z in points]


def _segment_triangles(z0, r0, z1, r1):
    """Return filled triangles for one profile segment (axis-mirrored).

    Vertices are ``(x, z)`` in profile space (tip at small z).
    """
    if abs(z0 - z1) <= 1e-12 and abs(r0 - r1) <= 1e-12:
        return []

    # Degenerate tip: collapse to a triangle from the axis point.
    if r0 <= 1e-12 and r1 <= 1e-12:
        return []
    if r0 <= 1e-12:
        return [((0.0, z0), (r1, z1), (-r1, z1))]
    if r1 <= 1e-12:
        return [((-r0, z0), (r0, z0), (0.0, z1))]

    # Two triangles for the quad (-r0,z0)-(r0,z0)-(r1,z1)-(-r1,z1).
    return [
        ((-r0, z0), (r0, z0), (r1, z1)),
        ((-r0, z0), (r1, z1), (-r1, z1)),
    ]


def _triangulate(profile, shank_start):
    """Split the mirrored silhouette into flute and shank triangle lists.

    Each triangle is a 3-tuple of ``(x, z)`` points in profile space.
    """
    flute = []
    shank = []
    if len(profile) < 2:
        return flute, shank

    for i in range(len(profile) - 1):
        z0, r0 = profile[i]
        z1, r1 = profile[i + 1]
        tris = _segment_triangles(z0, r0, z1, r1)
        if not tris:
            continue
        # Segment starting at index i is flute when i < shank_start.
        target = shank if i >= shank_start else flute
        target.extend(tris)
    return flute, shank


def _outline_polyline(profile):
    """Closed outline of the mirrored silhouette in profile ``(x, z)`` space.

    Order: tip -> right edge up -> left edge down. Suitable for a Line strip
    after normalization.

    Consecutive duplicate rings (used as flute/shank color boundaries in the
    3D profile) are collapsed — zero-length Line segments can make Kivy skip
    drawing the whole stroke.
    """
    if not profile:
        return []

    def _dedupe(points):
        out = []
        for pt in points:
            if out and abs(out[-1][0] - pt[0]) <= 1e-12 and abs(out[-1][1] - pt[1]) <= 1e-12:
                continue
            out.append(pt)
        return out

    right = _dedupe([(r, z) for z, r in profile])
    left = _dedupe([(-r, z) for z, r in reversed(profile)])
    # Drop the duplicated tip / top when both sides meet on the axis.
    if right and left and abs(right[0][0]) <= 1e-12:
        left = left[:-1] if left and abs(left[-1][0]) <= 1e-12 else left
    if right and left and abs(right[-1][0]) <= 1e-12 and abs(left[0][0]) <= 1e-12:
        left = left[1:]
    return right + left


def build_icon_geometry(tool_def, framing=FRAMING_THUMB, box_aspect=1.0):
    """Return silhouette geometry for ``tool_def`` in unit UV space.

    Returns a dict::

        {
            "flute_triangles": [((x,y), (x,y), (x,y)), ...],
            "shank_triangles": [...],
            "outline": [(x, y), ...],  # closed polyline in unit space
        }

    Tip is at the bottom. Coordinates are in ``[0, 1]`` UV space for a
    texture whose width/height ratio is ``box_aspect``.

    ``framing`` is ``"thumb"`` (tight tip crop) or ``"body"`` (more shank).
    """
    if framing not in (FRAMING_THUMB, FRAMING_BODY):
        framing = FRAMING_THUMB

    profile, shank_start = _tool_profile_with_shank(tool_def, scale=1.0)
    z_crop = _crop_z(profile, shank_start, framing=framing)
    cropped, cropped_shank = _crop_profile(profile, shank_start, z_crop)

    flute_raw, shank_raw = _triangulate(cropped, cropped_shank)
    outline_raw = _outline_polyline(cropped)

    # Collect every vertex so one normalization pass keeps fill + outline
    # in lockstep.
    all_points = []
    for tri in flute_raw:
        all_points.extend(tri)
    for tri in shank_raw:
        all_points.extend(tri)
    outline_start = len(all_points)
    all_points.extend(outline_raw)

    normalized = _normalize_points(all_points, box_aspect=box_aspect)

    def _take_tris(raw, offset):
        out = []
        for i, _tri in enumerate(raw):
            base = offset + 3 * i
            out.append((normalized[base], normalized[base + 1], normalized[base + 2]))
        return out

    flute_tris = _take_tris(flute_raw, 0)
    shank_tris = _take_tris(shank_raw, 3 * len(flute_raw))
    outline = normalized[outline_start:]
    if outline and outline[0] != outline[-1]:
        outline = list(outline) + [outline[0]]

    return {
        "flute_triangles": flute_tris,
        "shank_triangles": shank_tris,
        "outline": outline,
    }


def geometry_to_mesh(geometry, x, y, width, height):
    """Map unit-space geometry into widget coords for Kivy Mesh / Line.

    Returns ``(flute_vertices, flute_indices, shank_vertices, shank_indices,
    outline_points)`` where vertices are flat ``[x, y, u, v, ...]`` lists
    (Kivy default vertex format), indices are ``list(range(n))`` for
    ``mode='triangles'``, and outline points are a flat ``[x, y, ...]``
    list for ``Line(points=...)``.
    """

    def _tri_mesh(triangles):
        vertices = []
        for tri in triangles:
            for px, py in tri:
                vertices.extend((x + px * width, y + py * height, 0.0, 0.0))
        indices = list(range(len(triangles) * 3))
        return vertices, indices

    flute_vertices, flute_indices = _tri_mesh(geometry.get("flute_triangles", ()))
    shank_vertices, shank_indices = _tri_mesh(geometry.get("shank_triangles", ()))
    outline_points = []
    for px, py in geometry.get("outline", ()):
        outline_points.extend((x + px * width, y + py * height))
    return flute_vertices, flute_indices, shank_vertices, shank_indices, outline_points


def geometry_cache_key(tool_def, framing=FRAMING_THUMB):
    """Stable signature of the geometry-relevant fields on ``tool_def``."""
    if tool_def is None:
        return (framing, "__default__")
    return (
        framing,
        getattr(tool_def, "tool_type", None),
        getattr(tool_def, "diameter", None),
        getattr(tool_def, "shank_diameter", None),
        getattr(tool_def, "tip_diameter", None),
        getattr(tool_def, "corner_radius", None),
        getattr(tool_def, "taper_angle_deg", None),
        getattr(tool_def, "length", None),
        getattr(tool_def, "flute_length", None),
        getattr(tool_def, "shoulder_length", None),
        getattr(tool_def, "thread_depth", None),
        getattr(tool_def, "thread_pitch", None),
    )
