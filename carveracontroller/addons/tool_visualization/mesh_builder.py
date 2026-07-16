"""Procedural generation of very basic 3D tool meshes.
Each tool is approximated by revolving a simple 2D profile.
"""

import math

from carveracontroller.addons.tool_visualization.tool_definition import ToolType

VERTEX_FORMAT = [(b"v_pos", 3, "float"), (b"v_normal", 3, "float"), (b"v_tc0", 2, "float")]
RADIAL_SEGMENTS = 20
ROUND_SEGMENTS = 10
DEFAULT_TAPER_ANGLE_DEG = 30.0

# Factor used to compute the shared tool height from the largest diameter in the table.
LENGTH_DIAMETER_FACTOR = 3.0

# Minimum radius and length for tools to be visible on screen.
MIN_VISIBLE_RADIUS = 0.02
MIN_SHANK_LENGTH = 0.05

# Fixed on-screen size for tools with no CAM metadata (scaled viewer coordinates).
FALLBACK_TOOL_DISPLAY_RADIUS = 0.04
FALLBACK_TOOL_DISPLAY_HEIGHT = 1.3


def _segment_tangent(profile, start, end):
    z0, r0 = profile[start]
    z1, r1 = profile[end]
    return (z1 - z0, r1 - r0)


def _ring_tangent(profile, index):
    """Tangent in the (z, radius) plane used for normals at a profile ring."""
    z, r = profile[index]
    if r <= 1e-9:
        if index + 1 < len(profile):
            return _segment_tangent(profile, index, index + 1)
        return _segment_tangent(profile, index - 1, index)
    if index > 0 and profile[index - 1][1] <= 1e-9:
        return _segment_tangent(profile, index - 1, index)
    if index + 1 < len(profile) and profile[index + 1][1] <= 1e-9:
        return _segment_tangent(profile, index, index + 1)
    if index == 0:
        return _segment_tangent(profile, index, index + 1)
    if index == len(profile) - 1:
        return _segment_tangent(profile, index - 1, index)
    z_prev, r_prev = profile[index - 1]
    z_next, r_next = profile[index + 1]
    return (z_next - z_prev, r_next - r_prev)


def _surface_normal(dz, dr, theta):
    """Outward normal for a surface of revolution at angle theta.

    Derived from cross(circumferential_tangent, profile_tangent) for a profile
    segment with delta (dz, dr) in the (z, radius) plane.
    """
    nx = dz * math.cos(theta)
    ny = dz * math.sin(theta)
    nz = -dr
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def _add_vertex(positions, normals, x, y, z, nx, ny, nz):
    positions.extend([x, y, z])
    normals.extend([nx, ny, nz])
    return (len(positions) // 3) - 1


def _build_side_ring(positions, normals, z, radius, dz, dr, segments):
    """Add one ring of side-wall vertices with smooth analytical normals."""
    ring_indices = []
    for j in range(segments):
        theta = 2.0 * math.pi * j / segments
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        nx, ny, nz = _surface_normal(dz, dr, theta)
        idx = _add_vertex(positions, normals, radius * cos_t, radius * sin_t, z, nx, ny, nz)
        ring_indices.append(idx)
    return ring_indices


def _build_cap_ring(positions, normals, z, radius, nz_sign, segments):
    """Add a ring of cap vertices with a flat face normal (±Z)."""
    ring_indices = []
    for j in range(segments):
        theta = 2.0 * math.pi * j / segments
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        idx = _add_vertex(positions, normals, radius * cos_t, radius * sin_t, z, 0.0, 0.0, nz_sign)
        ring_indices.append(idx)
    return ring_indices


def _pack_vertices(positions, normals):
    vertices = []
    for i in range(len(positions) // 3):
        base = 3 * i
        vertices.extend(
            [
                positions[base],
                positions[base + 1],
                positions[base + 2],
                normals[base],
                normals[base + 1],
                normals[base + 2],
                0.0,
                0.0,
            ]
        )
    return vertices


def _build_revolve_mesh(profile, segments=RADIAL_SEGMENTS):
    """Revolve a `(z, radius)` profile (sorted by increasing z) into a triangle mesh.

    A profile point with `radius <= 0` is treated as a single point on the
    axis (e.g. a pointed tip, or the pole of a ball nose) rather than a ring.

    Vertices are indexed and share smooth analytical normals derived from the
    profile tangent. Flat end caps use separate vertices with ±Z normals.
    """
    if len(profile) < 2:
        raise ValueError("A tool profile needs at least two points")

    positions = []
    normals = []
    indices = []

    side_rings = []
    for i, (z, r) in enumerate(profile):
        if r <= 1e-9:
            side_rings.append(None)
        else:
            dz, dr = _ring_tangent(profile, i)
            side_rings.append(_build_side_ring(positions, normals, z, r, dz, dr, segments))

    # Side walls, connecting each consecutive pair of profile points.
    for i in range(len(profile) - 1):
        ring_a = side_rings[i]
        ring_b = side_rings[i + 1]
        if ring_a is None and ring_b is None:
            continue
        if ring_a is None:
            z_apex = profile[i][0]
            dz, dr = _segment_tangent(profile, i, i + 1)
            nx, ny, nz = _surface_normal(dz, dr, 0.0)
            apex_idx = _add_vertex(positions, normals, 0.0, 0.0, z_apex, nx, ny, nz)
            for j in range(segments):
                b0 = ring_b[j]
                b1 = ring_b[(j + 1) % segments]
                indices.extend([apex_idx, b0, b1])
        elif ring_b is None:
            z_apex = profile[i + 1][0]
            dz, dr = _segment_tangent(profile, i, i + 1)
            nx, ny, nz = _surface_normal(dz, dr, 0.0)
            apex_idx = _add_vertex(positions, normals, 0.0, 0.0, z_apex, nx, ny, nz)
            for j in range(segments):
                a0 = ring_a[j]
                a1 = ring_a[(j + 1) % segments]
                indices.extend([a0, a1, apex_idx])
        else:
            for j in range(segments):
                a0 = ring_a[j]
                a1 = ring_a[(j + 1) % segments]
                b1 = ring_b[(j + 1) % segments]
                b0 = ring_b[j]
                indices.extend([a0, a1, b1, a0, b1, b0])

    # Flat caps use their own vertices so side-wall normals are not overwritten.
    z_bottom, r_bottom = profile[0]
    if r_bottom > 1e-9:
        center_idx = _add_vertex(positions, normals, 0.0, 0.0, z_bottom, 0.0, 0.0, -1.0)
        cap_ring = _build_cap_ring(positions, normals, z_bottom, r_bottom, -1.0, segments)
        for j in range(segments):
            indices.extend([center_idx, cap_ring[(j + 1) % segments], cap_ring[j]])

    z_top, r_top = profile[-1]
    if r_top > 1e-9:
        center_idx = _add_vertex(positions, normals, 0.0, 0.0, z_top, 0.0, 0.0, 1.0)
        cap_ring = _build_cap_ring(positions, normals, z_top, r_top, 1.0, segments)
        for j in range(segments):
            indices.extend([center_idx, cap_ring[j], cap_ring[(j + 1) % segments]])

    return _pack_vertices(positions, normals), indices, VERTEX_FORMAT


def _tool_diameter(tool_def, scale):
    diameter = getattr(tool_def, "diameter", None) if tool_def else None
    if diameter and diameter > 0:
        return diameter
    return fallback_tool_dimensions(scale)[0]


def _effective_tool_diameter(tool_def, scale):
    """Return the outer cutting diameter used for sizing and proportions."""
    diameter = _tool_diameter(tool_def, scale)
    if tool_def and getattr(tool_def, "tool_type", None) is ToolType.RADIUS_MILL:
        corner_radius = getattr(tool_def, "corner_radius", None) or 0.0
        if corner_radius > 0:
            return diameter + 2.0 * corner_radius
    return diameter


def _profile_length(tool_def, scale, diameter, shared_length=None):
    if shared_length is not None and shared_length > 0:
        return shared_length
    if tool_def and getattr(tool_def, "diameter", None) and tool_def.diameter > 0:
        return diameter * LENGTH_DIAMETER_FACTOR
    return fallback_tool_dimensions(scale)[1]


def _safe_corner_radius(tool_def, diameter, tool_type=None):
    corner_radius = getattr(tool_def, "corner_radius", None) if tool_def else None
    if not corner_radius or corner_radius <= 0:
        return 0.0
    if tool_type is ToolType.RADIUS_MILL:
        return corner_radius
    return min(corner_radius, diameter / 2.0)


def _safe_taper_angle_deg(tool_def):
    angle = getattr(tool_def, "taper_angle_deg", None) if tool_def else None
    if angle is None or angle < 0 or angle >= 180:
        return DEFAULT_TAPER_ANGLE_DEG
    return angle


def _safe_thread_depth(tool_def, diameter):
    thread_depth = getattr(tool_def, "thread_depth", None) if tool_def else None
    if not thread_depth or thread_depth <= 0:
        # No parser-provided value: assume a sensible depth based on diameter.
        thread_depth = diameter / 10.0
    return min(thread_depth, diameter / 2.0)


def _safe_thread_pitch(tool_def, diameter):
    thread_pitch = getattr(tool_def, "thread_pitch", None) if tool_def else None
    if not thread_pitch or thread_pitch <= 0:
        # No parser-provided value: assume a sensible pitch based on diameter.
        thread_pitch = diameter / 5.0
    return thread_pitch


def _flat_end_mill_profile(diameter, length, **_kwargs):
    radius = diameter / 2.0
    return [(0.0, radius), (length, radius)]


def _thread_mill_profile(diameter, length, thread_depth=0.0, thread_pitch=0.0, **_kwargs):
    # Thread mills are represented as basic single-point cutters: a flat
    # minor-diameter base, rising over half a pitch to the major diameter
    # (the single cutting tooth), then back down to the minor diameter
    # before continuing as a plain cylindrical shank.
    major_radius = diameter / 2.0
    depth = thread_depth if thread_depth > 0 else diameter / 10.0
    depth = min(depth, major_radius)
    minor_radius = major_radius - depth

    pitch = thread_pitch if thread_pitch > 0 else diameter / 5.0
    pitch = min(pitch, length) if length > 0 else pitch
    half_pitch = pitch / 2.0

    points = [(0.0, minor_radius), (half_pitch, major_radius), (pitch, minor_radius)]
    if length > pitch:
        points.append((length, minor_radius))
    return points


def _ball_end_mill_profile(diameter, length, **_kwargs):
    radius = diameter / 2.0
    length = max(length, diameter)
    points = []
    for i in range(ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = radius * math.cos(theta)
        points.append((z, r))
    points.append((length, radius))
    return points


def _bull_nose_profile(diameter, length, corner_radius=0.0, **_kwargs):
    radius = diameter / 2.0
    corner_radius = corner_radius if corner_radius else radius * 0.25
    corner_radius = min(corner_radius, radius)
    flat_radius = radius - corner_radius

    points = [(0.0, max(flat_radius, 0.0))]
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = corner_radius + corner_radius * math.sin(theta)
        r = flat_radius + corner_radius * math.cos(theta)
        points.append((z, r))

    min_length = points[-1][0] + diameter * 0.5
    points.append((max(length, min_length), radius))
    return points


def _radius_mill_profile(diameter, length, corner_radius=0.0, **_kwargs):
    # For radius mills the supplied `diameter` is the flat-bottom diameter.
    # The outer cutting diameter is flat_diameter + 2 * corner_radius.
    flat_radius = diameter / 2.0
    corner_radius = corner_radius if corner_radius else flat_radius * 0.25
    full_radius = flat_radius + corner_radius
    full_diameter = diameter + 2.0 * corner_radius

    if corner_radius <= 1e-9:
        return _flat_end_mill_profile(diameter, length)

    # Concave corner arc: centre at (z=0, r=full_radius), sweeping from
    # the flat bottom out to the full cutting diameter.
    points = [(0.0, flat_radius)]
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = math.pi - (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = corner_radius * math.sin(theta)
        r = full_radius + corner_radius * math.cos(theta)
        points.append((z, r))

    min_length = points[-1][0] + full_diameter * 0.5
    points.append((max(length, min_length), full_radius))
    return points


def _chamfer_or_tapered_profile(diameter, length, taper_angle_deg=DEFAULT_TAPER_ANGLE_DEG, **_kwargs):
    """Pointed conical profile used for chamfer mills (and as the generic fallback)."""
    radius = diameter / 2.0
    half_angle_rad = math.radians(taper_angle_deg) / 2.0
    half_angle_rad = min(max(half_angle_rad, math.radians(5.0)), math.radians(85.0))
    cone_height = radius / math.tan(half_angle_rad)

    points = [(0.0, 0.0), (cone_height, radius)]
    if length > cone_height:
        points.append((length, radius))
    return points


def _tapered_mill_profile(diameter, length, corner_radius=0.0, taper_angle_deg=DEFAULT_TAPER_ANGLE_DEG, **_kwargs):
    """Bull-nose tip of diameter `D`, then a conical taper."""
    tip_radius = diameter / 2.0
    # Per-side angle from the axis (Fusion "Taper angle").
    alpha = math.radians(taper_angle_deg)
    alpha = min(max(alpha, 0.0), math.radians(85.0))

    max_corner = tip_radius / max(math.cos(alpha), 1e-6)
    corner_radius = min(max(corner_radius or 0.0, 0.0), max_corner)

    if corner_radius <= 1e-9:
        # Sharp flat tip at diameter D, then straight taper.
        points = [(0.0, tip_radius)]
        end_radius = tip_radius + length * math.tan(alpha)
        points.append((max(length, diameter * 0.5), end_radius))
        return points

    # Fillet between the flat tip and the cone: same construction as a bull
    # nose, but the arc stops at theta=-alpha where it meets the taper.
    flat_radius = tip_radius - corner_radius * math.cos(alpha)
    theta_start = -math.pi / 2.0
    theta_end = -alpha

    points = [(0.0, max(flat_radius, 0.0))]
    for i in range(1, ROUND_SEGMENTS + 1):
        t = i / ROUND_SEGMENTS
        theta = theta_start + (theta_end - theta_start) * t
        z = corner_radius + corner_radius * math.sin(theta)
        r = flat_radius + corner_radius * math.cos(theta)
        points.append((z, max(r, 0.0)))

    z_tan, r_tan = points[-1]
    # Continue along the taper for the remaining tool length.
    total_length = max(length, z_tan + diameter * 0.5)
    end_radius = r_tan + (total_length - z_tan) * math.tan(alpha)
    points.append((total_length, end_radius))
    return points


def _lollipop_profile(diameter, length, **_kwargs):
    """Full spherical cutter with a thinner cylindrical neck above the undercut."""
    radius = diameter / 2.0
    neck_radius = max(radius * 0.35, diameter * 0.15)
    neck_radius = min(neck_radius, radius * 0.95)
    theta_join = math.acos(neck_radius / radius)

    points = []
    # Lower hemisphere: south pole → equator (guarantees full cutting diameter).
    for i in range(ROUND_SEGMENTS + 1):
        theta = -math.pi / 2.0 + (math.pi / 2.0) * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = max(radius * math.cos(theta), 0.0)
        points.append((z, r))

    # Upper hemisphere: equator → neck join (skip duplicate equator point).
    for i in range(1, ROUND_SEGMENTS + 1):
        theta = theta_join * (i / ROUND_SEGMENTS)
        z = radius + radius * math.sin(theta)
        r = max(radius * math.cos(theta), 0.0)
        points.append((z, r))

    # Snap the join so the cylinder meets the ball at exactly neck_radius.
    ball_join_z = points[-1][0]
    points[-1] = (ball_join_z, neck_radius)

    total_length = max(length, ball_join_z + diameter * 0.5)
    points.append((total_length, neck_radius))
    return points


DEFAULT_PROFILE_BUILDER = _chamfer_or_tapered_profile
PROFILE_BUILDERS = {
    ToolType.FLAT_END_MILL: _flat_end_mill_profile,
    ToolType.THREAD_MILL: _thread_mill_profile,
    ToolType.BALL_END_MILL: _ball_end_mill_profile,
    ToolType.BULL_NOSE_END_MILL: _bull_nose_profile,
    ToolType.RADIUS_MILL: _radius_mill_profile,
    ToolType.CHAMFER_MILL: _chamfer_or_tapered_profile,
    ToolType.TAPERED_MILL: _tapered_mill_profile,
    ToolType.LOLLIPOP_MILL: _lollipop_profile,
}


def fallback_tool_dimensions(scale):
    """Return (diameter, length) in file units for the no-metadata fallback mesh.

    Values are chosen so that, after multiplication by `scale`, the mesh keeps
    a constant on-screen footprint regardless of file units or job bbox.
    """
    if not scale or scale <= 0:
        scale = 1.0
    diameter = FALLBACK_TOOL_DISPLAY_RADIUS * 2.0 / scale
    length = FALLBACK_TOOL_DISPLAY_HEIGHT / scale
    return diameter, length


def fallback_tool_profile(scale):
    """Pointed fallback profile with a fixed on-screen size."""
    diameter, length = fallback_tool_dimensions(scale)
    return _chamfer_or_tapered_profile(diameter, length)


def _reference_length(tool_table, scale):
    """Compute the shared tool height used for every tool in `tool_table`.
    This is required since the unit system of the document can vary.
    """
    diameters = [
        _effective_tool_diameter(tool_def, scale)
        for tool_def in tool_table.values()
        if tool_def and getattr(tool_def, "diameter", None) and tool_def.diameter > 0
    ]
    if diameters:
        return max(diameters) * LENGTH_DIAMETER_FACTOR
    return fallback_tool_dimensions(scale)[1]


def tool_profile(tool_def, length=None, scale=1.0):
    """Return the (unscaled) profile for a tool definition.
    Falls back to a basic pointed (chamfer-like) profile when `tool_def` is
    None or its type is unknown/unsupported (see DEFAULT_PROFILE_BUILDER).
    Missing diameters use the fixed on-screen fallback size.
    """
    diameter = _tool_diameter(tool_def, scale)
    effective_diameter = _effective_tool_diameter(tool_def, scale)
    length = _profile_length(tool_def, scale, effective_diameter, length)
    tool_type = getattr(tool_def, "tool_type", ToolType.UNKNOWN) if tool_def else ToolType.UNKNOWN
    corner_radius = _safe_corner_radius(tool_def, diameter, tool_type)
    taper_angle_deg = _safe_taper_angle_deg(tool_def)
    thread_depth = _safe_thread_depth(tool_def, diameter)
    thread_pitch = _safe_thread_pitch(tool_def, diameter)

    builder = PROFILE_BUILDERS.get(tool_type, DEFAULT_PROFILE_BUILDER)

    return builder(
        diameter,
        length,
        corner_radius=corner_radius,
        taper_angle_deg=taper_angle_deg,
        thread_depth=thread_depth,
        thread_pitch=thread_pitch,
    )


def _scale_profile(profile, scale, radius_boost):
    """Scale the profile by the given scale and radius boost."""
    factor = scale * radius_boost
    scaled_profile = [(z * factor, r * factor) for z, r in profile]

    total_length = scaled_profile[-1][0] if scaled_profile else 0.0
    if total_length < MIN_SHANK_LENGTH:
        shank_radius = scaled_profile[-1][1]
        scaled_profile = scaled_profile[:-1] + [(MIN_SHANK_LENGTH, shank_radius)]

    return scaled_profile


def _compute_radius_boost(profiles, scale):
    """Compute a single boost factor shared by every tool in `profiles`.

    Boosting each tool independently (to the same MIN_VISIBLE_RADIUS floor)
    would make different-sized tools appear identical on screen whenever
    they're all small enough to hit the floor. Instead we look at the
    *smallest* tool of the batch and compute one factor that makes it meet
    the visibility floor, then apply that same factor to every tool so their
    relative sizes stay accurate to each other.
    """
    radii = [max((r for _, r in profile), default=0.0) * scale for profile in profiles]
    radii = [r for r in radii if r > 1e-9]
    if not radii:
        return 1.0

    smallest_radius = min(radii)
    if smallest_radius < MIN_VISIBLE_RADIUS:
        return MIN_VISIBLE_RADIUS / smallest_radius
    return 1.0


def build_tool_mesh(tool_def, scale=1.0, radius_boost=1.0, length=None):
    profile = tool_profile(tool_def, length=length, scale=scale)
    scaled_profile = _scale_profile(profile, scale, radius_boost)
    return _build_revolve_mesh(scaled_profile)


def build_default_tool_mesh(scale=1.0, radius_boost=1.0):
    """Mesh used for tools with no metadata (fixed on-screen size)."""
    profile = fallback_tool_profile(scale)
    scaled_profile = _scale_profile(profile, scale, radius_boost)
    return _build_revolve_mesh(scaled_profile)


def build_tool_meshes(tool_table, scale=1.0):
    """Build a mesh for every tool in `tool_table`, plus a default mesh for
    tools with no metadata.

    Known tools share:
    - the same overall height, derived from the largest diameter in the
      table (see `_reference_length`) so it scales sensibly with the
      document's unit system instead of using a fixed absolute value.
    - a single radius boost factor derived from the smallest tool in the
      batch, so tiny tools stay visible without making unrelated tools look
      like they share the same diameter.

    The default (no-metadata) mesh keeps a fixed on-screen size, independent
    of file units.

    Returns `(tool_meshes, default_mesh)`.
    """
    default_profile = fallback_tool_profile(scale)

    if tool_table:
        shared_length = _reference_length(tool_table, scale)
        profiles = {
            number: tool_profile(tool_def, length=shared_length, scale=scale) for number, tool_def in tool_table.items()
        }
        radius_boost = _compute_radius_boost(list(profiles.values()), scale)
        tool_meshes = {
            number: _build_revolve_mesh(_scale_profile(profile, scale, radius_boost))
            for number, profile in profiles.items()
        }
    else:
        tool_meshes = {}

    default_mesh = _build_revolve_mesh(_scale_profile(default_profile, scale, 1.0))
    return tool_meshes, default_mesh
