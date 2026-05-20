"""Feature coordinate resolution, construction operations, and geometry types."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from carveracontroller.CNC import CNC

from .geometry import (
    circle_circle_intersections_2d,
    circle_line_intersections_2d,
    circumcircle_2d,
    ellipse_ellipse_intersections_2d,
    ellipse_line_intersections_2d,
    line_intersection_2d,
    midpoint_2d,
    tangent_circle_to_circle_external_2d,
    tangent_ellipse_to_ellipse_external_2d,
    tangent_point_to_circle_2d,
    tangent_point_to_ellipse_2d,
)
from .gcode import PROBE_VAR_CENTER_X, PROBE_VAR_CENTER_Y, PROBE_VAR_DIA_X, PROBE_VAR_DIA_Y
from .session import FeatureKind, ProbeScanFeature

_ERROR_INCOMPLETE_DATA = "Probe returned incomplete data."
_ERROR_INVALID_MISSING_DIAMETER = "Invalid or missing diameter in probe result."
_ERROR_PRESET_MISMATCH = "Probe result does not match selected probing option."

DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM = 0.02

XY = tuple[float, float]
CurveKind = Literal["circle", "ellipse"]
Curve = tuple[CurveKind, tuple[float, ...]]
TangentLine = tuple[XY, XY]


def mcs_xyz_to_wcs_xyz(mx: float, my: float, mz: float) -> tuple[float, float, float]:
    """Map a machine-space XYZ point into active work XYZ (same frame as offsets)."""
    theta = math.radians(float(CNC.vars.get("rotation_angle", 0.0)))
    wcox = float(CNC.vars.get("wcox", 0.0))
    wcoy = float(CNC.vars.get("wcoy", 0.0))
    wcoz = float(CNC.vars.get("wcoz", 0.0))
    dx = mx - wcox
    dy = my - wcoy
    c = math.cos(theta)
    s = math.sin(theta)
    wx = c * dx + s * dy
    wy = -s * dx + c * dy
    wz = mz - wcoz
    return wx, wy, wz


def index_by_id(features: Iterable[ProbeScanFeature]) -> dict[str, ProbeScanFeature]:
    return {f.id: f for f in features}


def diameters_equal(
    diameter_x: float,
    diameter_y: float,
    *,
    tolerance_mm: float,
) -> bool:
    """True when probed X/Y diameters represent a round bore within tolerance."""
    return abs(float(diameter_x) - float(diameter_y)) <= float(tolerance_mm)


def payload_referenced_feature_ids(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("a_id", "b_id", "segment_a_id", "segment_b_id",
                "point_id", "circle_id", "circle_a_id", "circle_b_id"):
        v = payload.get(key)
        if v:
            ids.append(str(v))
    verts = payload.get("vertex_feature_ids")
    if isinstance(verts, list):
        ids.extend(str(v) for v in verts if v)
    src = payload.get("source_ids")
    if isinstance(src, list):
        ids.extend(str(v) for v in src if v)
    return ids


def referenced_feature_ids(feature: ProbeScanFeature) -> list[str]:
    return payload_referenced_feature_ids(feature.payload)


def features_referencing_id(features: Iterable[ProbeScanFeature], target_id: str) -> list[str]:
    holders: list[str] = []
    for i, f in enumerate(features):
        if target_id in referenced_feature_ids(f):
            holders.append(f"{i + 1}. {f.label}")
    return holders


def kind_has_vertex_xy(f: ProbeScanFeature) -> bool:
    """True for feature kinds that expose an XY vertex (usable in constructions)."""
    return f.kind in (
        FeatureKind.POINT,
        FeatureKind.CORNER,
        FeatureKind.CIRCLE,
        FeatureKind.ELLIPSE,
        FeatureKind.DERIVED_POINT,
    )


def resolve_xy(vertex: ProbeScanFeature) -> XY | None:
    """Vertices for constructions: POINT, CORNER, curve centers, DERIVED_POINT."""
    p = vertex.payload
    if vertex.kind == FeatureKind.POINT:
        return float(p["x"]), float(p["y"])
    if vertex.kind == FeatureKind.CORNER:
        return float(p["x"]), float(p["y"])
    if vertex.kind in (FeatureKind.CIRCLE, FeatureKind.ELLIPSE, FeatureKind.DERIVED_CIRCLE):
        return float(p["cx"]), float(p["cy"])
    if vertex.kind == FeatureKind.DERIVED_POINT:
        return float(p["x"]), float(p["y"])
    return None


def segment_endpoints(
    by_id: dict[str, ProbeScanFeature],
    seg: ProbeScanFeature,
    resolve: Callable[[ProbeScanFeature], XY | None] = resolve_xy,
) -> tuple[XY, XY] | None:
    """Return ((x1,y1),(x2,y2)) for a SEGMENT feature."""
    if seg.kind != FeatureKind.SEGMENT:
        return None
    a = by_id.get(str(seg.payload.get("a_id", "")))
    b = by_id.get(str(seg.payload.get("b_id", "")))
    if not a or not b:
        return None
    pa = resolve(a)
    pb = resolve(b)
    if pa is None or pb is None:
        return None
    return pa, pb


def resolve_circle(feature: ProbeScanFeature) -> tuple[float, float, float] | None:
    """Return (cx, cy, r) for CIRCLE or DERIVED_CIRCLE features, else None."""
    p = feature.payload
    if feature.kind in (FeatureKind.CIRCLE, FeatureKind.DERIVED_CIRCLE):
        return (
            float(p.get("cx", 0.0)),
            float(p.get("cy", 0.0)),
            float(p.get("r", 0.0)),
        )
    return None


def resolve_ellipse(feature: ProbeScanFeature) -> tuple[float, float, float, float] | None:
    """Return (cx, cy, rx, ry) for ELLIPSE features, else None."""
    if feature.kind != FeatureKind.ELLIPSE:
        return None
    p = feature.payload
    return (
        float(p.get("cx", 0.0)),
        float(p.get("cy", 0.0)),
        float(p.get("diameter_x", 0.0)) / 2.0,
        float(p.get("diameter_y", 0.0)) / 2.0,
    )


def resolve_curve(feature: ProbeScanFeature) -> Curve | None:
    """Return ('circle', (cx,cy,r)) or ('ellipse', (cx,cy,rx,ry)) for curve features."""
    circ = resolve_circle(feature)
    if circ is not None:
        return ("circle", circ)
    ell = resolve_ellipse(feature)
    if ell is not None:
        return ("ellipse", ell)
    return None


def curve_to_ellipse_params(curve: Curve) -> tuple[float, float, float, float]:
    """Normalize circle or ellipse curve tuple to (cx, cy, rx, ry)."""
    kind, data = curve
    if kind == "circle":
        cx, cy, r = data
        return float(cx), float(cy), float(r), float(r)
    cx, cy, rx, ry = data
    return float(cx), float(cy), float(rx), float(ry)


def curve_line_intersections(
    curve: Curve,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> list[XY]:
    """Intersections of a circle or ellipse with the infinite line through A and B."""
    kind, data = curve
    if kind == "circle":
        return circle_line_intersections_2d(data[0], data[1], data[2], ax, ay, bx, by)
    cx, cy, rx, ry = curve_to_ellipse_params(curve)
    return ellipse_line_intersections_2d(cx, cy, rx, ry, ax, ay, bx, by)


def curve_curve_intersections(c1: Curve, c2: Curve) -> list[XY]:
    """Intersections of two circles or ellipses."""
    if c1[0] == "circle" and c2[0] == "circle":
        return circle_circle_intersections_2d(*c1[1], *c2[1])
    e1 = curve_to_ellipse_params(c1)
    e2 = curve_to_ellipse_params(c2)
    return ellipse_ellipse_intersections_2d(*e1, *e2)


def point_curve_tangents(px: float, py: float, curve: Curve) -> list[XY]:
    """Tangent touch-points on a circle or ellipse from an external point."""
    kind, data = curve
    if kind == "circle":
        return tangent_point_to_circle_2d(px, py, data[0], data[1], data[2])
    ecx, ecy, erx, ery = curve_to_ellipse_params(curve)
    return tangent_point_to_ellipse_2d(px, py, ecx, ecy, erx, ery)


def curve_curve_external_tangents(c1: Curve, c2: Curve) -> list[TangentLine]:
    """External tangent lines between two circles or ellipses."""
    if c1[0] == "circle" and c2[0] == "circle":
        return tangent_circle_to_circle_external_2d(*c1[1], *c2[1])
    e1 = curve_to_ellipse_params(c1)
    e2 = curve_to_ellipse_params(c2)
    return tangent_ellipse_to_ellipse_external_2d(*e1, *e2)


def _normalized_var_keys(var_keys: list[str]) -> set[str]:
    return {str(k).strip() for k in var_keys if str(k).strip()}


def _probe_axis_segment_bundle(
    segment_label: str,
    endpoint_a_label: str,
    endpoint_b_label: str,
    center_label: str,
    cx_m: float,
    cy_m: float,
    diameter: float,
    axis: Literal["x", "y"],
    *,
    include_center: bool = True,
    source: str,
) -> list[ProbeScanFeature]:
    """Horizontal (axis x) or vertical (axis y) chord: endpoints, segment, optional center."""
    half = float(diameter) / 2.0
    if axis == "x":
        x1_m, y1_m = cx_m - half, cy_m
        x2_m, y2_m = cx_m + half, cy_m
    else:
        x1_m, y1_m = cx_m, cy_m - half
        x2_m, y2_m = cx_m, cy_m + half
    wx1, wy1, _ = mcs_xyz_to_wcs_xyz(x1_m, y1_m, 0.0)
    wx2, wy2, _ = mcs_xyz_to_wcs_xyz(x2_m, y2_m, 0.0)
    pa = ProbeScanFeature.new_point(
        endpoint_a_label,
        wx1,
        wy1,
        0.0,
        source=source,
    )
    pb = ProbeScanFeature.new_point(
        endpoint_b_label,
        wx2,
        wy2,
        0.0,
        source=source,
    )
    seg = ProbeScanFeature.new_segment(segment_label, pa.id, pb.id)
    out: list[ProbeScanFeature] = [pa, pb, seg]
    if include_center:
        mx_w, my_w = midpoint_2d(wx1, wy1, wx2, wy2)
        out.append(
            ProbeScanFeature.new_derived_point(center_label, pa.id, pb.id, mx_w, my_w)
        )
    return out


def _probe_rect_cross_features(
    h_segment_label: str,
    h_endpoint_a_label: str,
    h_endpoint_b_label: str,
    v_segment_label: str,
    v_endpoint_a_label: str,
    v_endpoint_b_label: str,
    center_label: str,
    cx_m: float,
    cy_m: float,
    diameter_x: float,
    diameter_y: float,
    *,
    source: str,
) -> list[ProbeScanFeature]:
    """Two orthogonal chords (horizontal + vertical) and one shared center point."""
    h_bundle = _probe_axis_segment_bundle(
        h_segment_label,
        h_endpoint_a_label,
        h_endpoint_b_label,
        center_label,
        cx_m,
        cy_m,
        diameter_x,
        "x",
        include_center=False,
        source=source,
    )
    v_bundle = _probe_axis_segment_bundle(
        v_segment_label,
        v_endpoint_a_label,
        v_endpoint_b_label,
        center_label,
        cx_m,
        cy_m,
        diameter_y,
        "y",
        include_center=False,
        source=source,
    )
    pa, pb = h_bundle[0], h_bundle[1]
    wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
    center = ProbeScanFeature.new_derived_point(center_label, pa.id, pb.id, wx, wy)
    return h_bundle + v_bundle + [center]


def _features_circle_or_ellipse(
    label: str,
    cx_m: float,
    cy_m: float,
    diameter_x: float,
    diameter_y: float,
    *,
    tolerance_mm: float,
) -> tuple[list[ProbeScanFeature], str | None]:
    wx, wy, _ = mcs_xyz_to_wcs_xyz(cx_m, cy_m, 0.0)
    if diameters_equal(diameter_x, diameter_y, tolerance_mm=tolerance_mm):
        r = diameter_x / 2.0
        if r <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        return (
            [ProbeScanFeature.new_circle(label, wx, wy, r)],
            None,
        )
    if diameter_x <= 0 or diameter_y <= 0:
        return [], _ERROR_INVALID_MISSING_DIAMETER
    return (
        [
            ProbeScanFeature.new_ellipse(label, wx, wy, diameter_x, diameter_y)
        ],
        None,
    )


def features_from_m461_m462(
    vd: dict[str, float],
    var_keys: list[str],
    *,
    preset: str,
    mx: float,
    my: float,
    segment_label: str,
    endpoint_a_label: str,
    endpoint_b_label: str,
    center_label: str,
    h_segment_label: str,
    h_endpoint_a_label: str,
    h_endpoint_b_label: str,
    v_segment_label: str,
    v_endpoint_a_label: str,
    v_endpoint_b_label: str,
    curve_label: str,
    source: str,
    tolerance_mm: float | None = None,
) -> tuple[list[ProbeScanFeature], str | None]:
    """
    Build probe-scan features from M461/M462 variables and UI preset.

    Returns (features, error_message). On success error_message is None.
    """
    keys = _normalized_var_keys(var_keys)

    if preset == "CenterX":
        if keys != {PROBE_VAR_DIA_X, PROBE_VAR_CENTER_X}:
            return [], _ERROR_PRESET_MISMATCH
        if PROBE_VAR_DIA_X not in vd or PROBE_VAR_CENTER_X not in vd:
            return [], _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        if d_x <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y]) if PROBE_VAR_CENTER_Y in vd else float(my)
        return (
            _probe_axis_segment_bundle(
                segment_label,
                endpoint_a_label,
                endpoint_b_label,
                center_label,
                cx_m,
                cy_m,
                d_x,
                "x",
                source=source,
            ),
            None,
        )

    if preset == "CenterY":
        if keys != {PROBE_VAR_DIA_Y, PROBE_VAR_CENTER_Y}:
            return [], _ERROR_PRESET_MISMATCH
        if PROBE_VAR_DIA_Y not in vd or PROBE_VAR_CENTER_Y not in vd:
            return [], _ERROR_INCOMPLETE_DATA
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_y <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cy_m = float(vd[PROBE_VAR_CENTER_Y])
        cx_m = float(vd[PROBE_VAR_CENTER_X]) if PROBE_VAR_CENTER_X in vd else float(mx)
        return (
            _probe_axis_segment_bundle(
                segment_label,
                endpoint_a_label,
                endpoint_b_label,
                center_label,
                cx_m,
                cy_m,
                d_y,
                "y",
                source=source,
            ),
            None,
        )

    if preset in ("CenterBore", "CenterBoss", "CenterPocket", "CenterBlock"):
        required_keys = {
            PROBE_VAR_DIA_X,
            PROBE_VAR_DIA_Y,
            PROBE_VAR_CENTER_X,
            PROBE_VAR_CENTER_Y,
        }
        if keys != required_keys:
            return [], _ERROR_PRESET_MISMATCH
        if not all(k in vd for k in required_keys):
            return [], _ERROR_INCOMPLETE_DATA
        d_x = float(vd[PROBE_VAR_DIA_X])
        d_y = float(vd[PROBE_VAR_DIA_Y])
        if d_x <= 0 and d_y <= 0:
            return [], _ERROR_INVALID_MISSING_DIAMETER
        cx_m = float(vd[PROBE_VAR_CENTER_X])
        cy_m = float(vd[PROBE_VAR_CENTER_Y])

        if preset in ("CenterPocket", "CenterBlock"):
            if d_x <= 0 or d_y <= 0:
                return [], _ERROR_INVALID_MISSING_DIAMETER
            return (
                _probe_rect_cross_features(
                    h_segment_label,
                    h_endpoint_a_label,
                    h_endpoint_b_label,
                    v_segment_label,
                    v_endpoint_a_label,
                    v_endpoint_b_label,
                    center_label,
                    cx_m,
                    cy_m,
                    d_x,
                    d_y,
                    source=source,
                ),
                None,
            )

        classify_tol = (
            tolerance_mm
            if tolerance_mm is not None
            else DEFAULT_CIRCLE_CLASSIFY_TOLERANCE_MM
        )
        return _features_circle_or_ellipse(
            curve_label,
            cx_m,
            cy_m,
            d_x,
            d_y,
            tolerance_mm=classify_tol,
        )

    return [], _ERROR_PRESET_MISMATCH


@dataclass
class PointGeom:
    x: float
    y: float
    kind: FeatureKind  # POINT, CORNER, or DERIVED_POINT


@dataclass
class CircleGeom:
    cx: float
    cy: float
    rx: float
    ry: float  # rx == ry for circles/derived-circles; differs for ellipses
    kind: FeatureKind  # CIRCLE, ELLIPSE, or DERIVED_CIRCLE


@dataclass
class SegmentGeom:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class PolylineGeom:
    vertices: list[tuple[float, float]]
    closed: bool


@dataclass
class LabelGeom:
    x: float
    y: float
    text: str
    kind: FeatureKind  # ANGLE (text at probe site)


FeatureGeom = PointGeom | CircleGeom | SegmentGeom | PolylineGeom | LabelGeom | None


def resolve_geometry(
    feature: ProbeScanFeature,
    by_id: dict[str, ProbeScanFeature],
) -> FeatureGeom:
    """Map a feature to a typed geometry value for drawing and hit-testing.

    Returns None when the geometry cannot be resolved (e.g. ANGLE features
    without coordinates, missing references, or incomplete payloads).
    """
    p = feature.payload
    k = feature.kind

    if k == FeatureKind.POINT:
        try:
            return PointGeom(float(p["x"]), float(p["y"]), k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.CORNER:
        try:
            return PointGeom(float(p["x"]), float(p["y"]), k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.DERIVED_POINT:
        try:
            return PointGeom(float(p["x"]), float(p["y"]), k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.CIRCLE:
        try:
            r = float(p["r"])
            return CircleGeom(float(p["cx"]), float(p["cy"]), r, r, k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.DERIVED_CIRCLE:
        try:
            r = float(p["r"])
            return CircleGeom(float(p["cx"]), float(p["cy"]), r, r, k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.ELLIPSE:
        try:
            rx = float(p["diameter_x"]) / 2.0
            ry = float(p["diameter_y"]) / 2.0
            return CircleGeom(float(p["cx"]), float(p["cy"]), rx, ry, k)
        except (KeyError, TypeError, ValueError):
            return None

    if k == FeatureKind.SEGMENT:
        ends = segment_endpoints(by_id, feature)
        if ends is None:
            return None
        (x1, y1), (x2, y2) = ends
        return SegmentGeom(x1, y1, x2, y2)

    if k == FeatureKind.POLYLINE:
        vids = p.get("vertex_feature_ids")
        if not isinstance(vids, list) or len(vids) < 2:
            return None
        verts: list[tuple[float, float]] = []
        for vid in vids:
            vf = by_id.get(str(vid))
            if vf is None:
                return None
            xy = resolve_xy(vf)
            if xy is None:
                return None
            verts.append(xy)
        return PolylineGeom(verts, bool(p.get("closed", False)))

    if k == FeatureKind.ANGLE:
        try:
            x = float(p["x"])
            y = float(p["y"])
            deg = float(p["degrees"])
        except (KeyError, TypeError, ValueError):
            return None
        return LabelGeom(x, y, f"{deg:.3f}\u00b0", k)

    return None


def construct_segment(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    label: str = "Segment",
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create a SEGMENT from exactly two point-like selected features."""
    if len(selection_ids) != 2:
        return [], "Select exactly two point features."
    by_id = index_by_id(features)
    a = by_id.get(selection_ids[0])
    b = by_id.get(selection_ids[1])
    if not a or not b:
        return [], "Missing features for segment."
    if not kind_has_vertex_xy(a) or not kind_has_vertex_xy(b):
        return [], "Segments need point-like features (corner, center point, probe point\u2026)."
    if resolve_xy(a) is None or resolve_xy(b) is None:
        return [], "Could not resolve XY for selected features."
    return [ProbeScanFeature.new_segment(label, selection_ids[0], selection_ids[1])], None


def construct_polyline(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    label: str = "Polyline",
    closed: bool = False,
    min_verts_error: str | None = None,
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create a POLYLINE from 2+ (open) or 3+ (closed) point-like selected features."""
    min_n = 3 if closed else 2
    if len(selection_ids) < min_n:
        return [], min_verts_error or f"Select at least {min_n} vertices in checkbox order."
    by_id = index_by_id(features)
    for fid in selection_ids:
        f = by_id.get(fid)
        if not f or not kind_has_vertex_xy(f) or resolve_xy(f) is None:
            return [], "Polyline needs point-like features only (wrong selection)."
    return [ProbeScanFeature.new_polyline(label, selection_ids, closed=closed)], None


def construct_circumcircle(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    label: str = "Circumcircle",
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create a DERIVED_CIRCLE (circumcircle) from exactly three point features."""
    if len(selection_ids) != 3:
        return [], "Select exactly three point features."
    by_id = index_by_id(features)
    pts_xy: list[tuple[float, float]] = []
    for fid in selection_ids:
        f = by_id.get(fid)
        xy = resolve_xy(f) if f else None
        if xy is None:
            return [], "Circumcircle needs three resolvable XY points."
        pts_xy.append(xy)
    try:
        (ax, ay), (bx, by), (cx, cy) = pts_xy
        ucx, ucy, r = circumcircle_2d(ax, ay, bx, by, cx, cy)
    except ValueError as e:
        if str(e) == "colinear_points":
            return [], "Points are colinear, cannot form a circle."
        return [], str(e)
    return [
        ProbeScanFeature.new_derived_circle(
            label,
            (selection_ids[0], selection_ids[1], selection_ids[2]),
            ucx,
            ucy,
            r,
        )
    ], None


def construct_intersection(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    intersection_base_label: str = "Intersection",
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create DERIVED_POINT(s) at the intersection of two segments, curves, or mixed."""

    if len(selection_ids) != 2:
        return [], "Select exactly two features."
    by_id = index_by_id(features)
    f1, f2 = by_id.get(selection_ids[0]), by_id.get(selection_ids[1])
    if not f1 or not f2:
        return [], "Missing features for intersection."

    def _is_seg(f: ProbeScanFeature) -> bool:
        return f.kind == FeatureKind.SEGMENT

    new_pts: list[tuple[float, float]] = []

    if _is_seg(f1) and _is_seg(f2):
        e1 = segment_endpoints(by_id, f1)
        e2 = segment_endpoints(by_id, f2)
        if not e1 or not e2:
            return [], "Segment endpoints could not be resolved."
        (x1, y1), (x2, y2) = e1
        (x3, y3), (x4, y4) = e2
        hit = line_intersection_2d(x1, y1, x2, y2, x3, y3, x4, y4)
        if hit is None:
            return [], "Lines are parallel, no intersection point."
        new_pts = [hit]

    elif (resolve_curve(f1) and _is_seg(f2)) or (_is_seg(f1) and resolve_curve(f2)):
        fc, fl = (f1, f2) if resolve_curve(f1) else (f2, f1)
        curve = resolve_curve(fc)
        ends = segment_endpoints(by_id, fl)
        if curve is None or ends is None:
            return [], "Could not resolve curve/segment geometry."
        (ax, ay), (bx, by_) = ends
        new_pts = curve_line_intersections(curve, ax, ay, bx, by_)
        if not new_pts:
            return [], "Curve and line do not intersect."

    elif resolve_curve(f1) and resolve_curve(f2):
        c1 = resolve_curve(f1)
        c2 = resolve_curve(f2)
        if c1 is None or c2 is None:
            return [], "Could not resolve curve geometry."
        new_pts = curve_curve_intersections(c1, c2)
        if not new_pts:
            return [], "Curves do not intersect."
    else:
        return [], "Select two segments, two curves, or a curve and a segment."

    new_feats: list[ProbeScanFeature] = []
    for i, (ix, iy) in enumerate(new_pts):
        lbl = (
            f"{intersection_base_label} {i + 1}"
            if len(new_pts) > 1
            else intersection_base_label
        )
        new_feats.append(
            ProbeScanFeature.new_derived_point(lbl, f1.id, f2.id, ix, iy)
        )
    return new_feats, None


def construct_midpoint(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    label: str = "Midpoint",
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create a DERIVED_POINT at the midpoint of two point-like features."""
    if len(selection_ids) != 2:
        return [], "Select exactly two point features."
    by_id = index_by_id(features)
    fa, fb = by_id.get(selection_ids[0]), by_id.get(selection_ids[1])
    if not fa or not fb:
        return [], "Missing features for midpoint."
    pa, pb = resolve_xy(fa), resolve_xy(fb)
    if pa is None or pb is None:
        return [], "Could not resolve XY for selected features."
    mx, my = midpoint_2d(pa[0], pa[1], pb[0], pb[1])
    return [ProbeScanFeature.new_derived_point(label, fa.id, fb.id, mx, my)], None


def construct_tangent(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    *,
    tangent_point_label: Callable[[int], str] | None = None,
    tangent_line_label: Callable[[int], str] | None = None,
    tangent_a_label: Callable[[int], str] | None = None,
    tangent_b_label: Callable[[int], str] | None = None,
) -> tuple[list[ProbeScanFeature], str | None]:
    """Create tangent derived points (and segment) from a point+curve or two curves."""
    if tangent_point_label is None:
        tangent_point_label = lambda n: f"Tangent point {n}"
    if tangent_line_label is None:
        tangent_line_label = lambda n: f"Tangent {n}"
    if tangent_a_label is None:
        tangent_a_label = lambda n: f"Tangent {n}\u00b7A"
    if tangent_b_label is None:
        tangent_b_label = lambda n: f"Tangent {n}\u00b7B"

    if len(selection_ids) != 2:
        return [], "Select a point + curve, or two curves."
    by_id = index_by_id(features)
    f1, f2 = by_id.get(selection_ids[0]), by_id.get(selection_ids[1])
    if not f1 or not f2:
        return [], "Missing features for tangent."

    def _is_pt(f: ProbeScanFeature) -> bool:
        return (
            f.kind in (FeatureKind.POINT, FeatureKind.CORNER, FeatureKind.DERIVED_POINT)
            and resolve_xy(f) is not None
        )

    c1 = resolve_curve(f1)
    c2 = resolve_curve(f2)

    if _is_pt(f1) and c2 is not None:
        pt_feat, curve_feat, curve = f1, f2, c2
    elif c1 is not None and _is_pt(f2):
        pt_feat, curve_feat, curve = f2, f1, c1
    elif c1 is not None and c2 is not None:
        pt_feat = curve_feat = curve = None  # type: ignore[assignment]
    else:
        return [], "Select a point + curve, or two curves."

    new_feats: list[ProbeScanFeature] = []

    if pt_feat is not None and curve_feat is not None and curve is not None:
        pxy = resolve_xy(pt_feat)
        if pxy is None:
            return [], "Could not resolve geometry."
        px_, py_ = pxy
        touch_pts = point_curve_tangents(px_, py_, curve)
        if not touch_pts:
            if curve[0] == "circle":
                return [], "Point is inside the circle \u2014 no tangent exists."
            return [], "Point is inside the ellipse \u2014 no tangent exists."
        for i, (tx, ty) in enumerate(touch_pts):
            new_feats.append(
                ProbeScanFeature.new_derived_point(
                    tangent_point_label(i + 1), pt_feat.id, curve_feat.id, tx, ty
                )
            )

    elif c1 is not None and c2 is not None:
        tangent_lines = curve_curve_external_tangents(c1, c2)
        if not tangent_lines:
            if c1[0] == "circle" and c2[0] == "circle":
                return [], "Circles are concentric \u2014 no external tangent exists."
            return [], "Ellipses have no external tangent."
        for i, (tp1, tp2) in enumerate(tangent_lines):
            dp1 = ProbeScanFeature.new_derived_point(
                tangent_a_label(i + 1), f1.id, f2.id, tp1[0], tp1[1]
            )
            dp2 = ProbeScanFeature.new_derived_point(
                tangent_b_label(i + 1), f1.id, f2.id, tp2[0], tp2[1]
            )
            new_feats.extend([
                dp1,
                dp2,
                ProbeScanFeature.new_segment(tangent_line_label(i + 1), dp1.id, dp2.id),
            ])

    return new_feats, None


@dataclass
class ConstructButtonStates:
    has_selection: bool = False
    can_segment: bool = False
    can_polyline_open: bool = False
    can_polyline_closed: bool = False
    can_circumcircle: bool = False
    can_intersection: bool = False
    can_midpoint: bool = False
    can_tangent: bool = False


def compute_construct_button_states(
    features: list[ProbeScanFeature],
    selection_ids: list[str],
    is_probing: bool,
) -> ConstructButtonStates:
    """Compute which construction buttons should be enabled for the current selection."""
    if is_probing:
        return ConstructButtonStates()

    by_id = index_by_id(features)
    ids = list(selection_ids)
    n = len(ids)
    states = ConstructButtonStates(has_selection=n > 0)

    def is_point_like(fid: str) -> bool:
        f = by_id.get(fid)
        return f is not None and kind_has_vertex_xy(f) and resolve_xy(f) is not None

    def is_segment(fid: str) -> bool:
        f = by_id.get(fid)
        return f is not None and f.kind == FeatureKind.SEGMENT

    def is_curve_like(fid: str) -> bool:
        f = by_id.get(fid)
        return f is not None and resolve_curve(f) is not None

    states.can_segment = n == 2 and all(is_point_like(fid) for fid in ids)
    states.can_polyline_open = n >= 2 and all(is_point_like(fid) for fid in ids)
    states.can_polyline_closed = n >= 3 and all(is_point_like(fid) for fid in ids)
    states.can_circumcircle = n == 3 and all(is_point_like(fid) for fid in ids)
    states.can_intersection = n == 2 and (
        all(is_segment(fid) for fid in ids)
        or all(is_curve_like(fid) for fid in ids)
        or (is_curve_like(ids[0]) and is_segment(ids[1]))
        or (is_segment(ids[0]) and is_curve_like(ids[1]))
    )
    states.can_midpoint = n == 2 and all(is_point_like(fid) for fid in ids)
    states.can_tangent = n == 2 and (
        (is_point_like(ids[0]) and is_curve_like(ids[1]))
        or (is_curve_like(ids[0]) and is_point_like(ids[1]))
        or all(is_curve_like(fid) for fid in ids)
    )
    return states
